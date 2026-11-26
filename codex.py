"""Codex CLI / app usage: daily API-price cost and plan limits, both from Codex's session rollouts.

Rollouts:  <codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]  (and archived_sessions/)
  token_usage_record   one per API response: response_id + token usage
  turn_context         the model used for the following turn
  event_msg/token_count  carries rate_limits: used_percent, window_minutes, resets_at
<codex home> is $codex_home (workflow setting), else $CODEX_HOME, else ~/.codex.
Compressed rollouts need the zstd command (brew install zstd).
"""
from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from usage import cached_scan, merge_entries, merge_request

CACHE_VERSION = 5
# Early rollouts (2025) often don't name the model; Codex defaulted to gpt-5 / gpt-5-codex (same price).
DEFAULT_MODEL = "gpt-5"

# (model slug pattern, input, cached input, output) in USD per million tokens, first match wins.
# Requests over 272K input tokens use the long-context rates (LONG) where a model has them.
# Source: developers.openai.com/api/docs/pricing, November 2026 (GPT-5.6 Sol at its promotional price).
PRICES: List[Tuple[str, float, float, float]] = [
    (r"^gpt-6\.2-astra", 8.00, 0.40, 40.00),
    (r"^gpt-6\.2-sol", 2.00, 0.10, 10.00),
    (r"^gpt-6\.1-sol", 2.00, 0.10, 10.00),
    (r"^gpt-6\.1-terra", 1.00, 0.05, 5.00),
    (r"^gpt-6-astra", 10.00, 1.00, 50.00),
    (r"^gpt-6-sol", 2.00, 0.20, 10.00),
    (r"^gpt-6-luna", 0.10, 0.01, 0.50),
    (r"^gpt-5\.6-sol", 4.00, 0.40, 20.00),
    (r"^gpt-5\.6-terra", 2.00, 0.20, 12.00),
    (r"^gpt-5\.6-luna", 0.20, 0.02, 1.20),
    (r"^gpt-5\.5", 5.00, 0.50, 30.00),
    (r"^gpt-5\.4-mini", 0.75, 0.075, 4.50),
    (r"^gpt-5\.4-nano", 0.20, 0.02, 1.25),
    (r"^gpt-5\.4", 2.50, 0.25, 15.00),
    (r"^gpt-5\.[23]", 1.75, 0.175, 14.00),
    (r"^gpt-5-mini", 0.25, 0.025, 2.00),
    (r"^gpt-5-nano", 0.05, 0.005, 0.40),
    (r"^gpt-5(\.1)?(-codex)?(-|$)", 1.25, 0.125, 10.00),
]
_PRICE_RES = [(re.compile(p), i, c, o) for p, i, c, o in PRICES]
LONG_CONTEXT = 272_000
LONG_MULTIPLIER = {"input": 2.0, "output": 1.5}  # long-context rates are 2x input/cached, 1.5x output
NO_LONG_CONTEXT = re.compile(r"mini|nano|gpt-5\.[23]|gpt-5(\.1)?(-codex)?(-|$)")


def codex_home() -> Path:
    raw = os.environ.get("codex_home") or os.environ.get("CODEX_HOME") or "~/.codex"
    return Path(raw).expanduser()


def zstd_path() -> Optional[str]:
    for candidate in ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("zstd")


def request_cost(model: str, usage: dict) -> Optional[float]:
    for rx, pin, pcached, pout in _PRICE_RES:
        if rx.search(model or ""):
            break
    else:
        return None
    inp = usage.get("input_tokens", 0)  # includes cached input
    cached = usage.get("cached_input_tokens", 0)
    out = usage.get("output_tokens", 0)  # includes reasoning
    if not all(isinstance(n, int) and n >= 0 for n in (inp, cached, out)):
        return None
    cached = min(cached, inp)
    if inp > LONG_CONTEXT and not NO_LONG_CONTEXT.search(model):
        pin, pcached = pin * LONG_MULTIPLIER["input"], pcached * LONG_MULTIPLIER["input"]
        pout *= LONG_MULTIPLIER["output"]
    return ((inp - cached) * pin + cached * pcached + out * pout) / 1e6


def _epoch(ts: str) -> Optional[int]:
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError, OverflowError, OSError):
        return None


def _read(path: Path) -> bytes:
    if path.suffix == ".zst":
        zstd = zstd_path()
        if not zstd:
            raise OSError("zstd not installed")
        return subprocess.run([zstd, "-dcq", str(path)], capture_output=True, check=True, timeout=30).stdout
    return path.read_bytes()


def _scan_file(path: Path, prev: Optional[dict]) -> dict:
    st = path.stat()
    if prev and prev.get("m") == st.st_mtime_ns and prev.get("s") == st.st_size:
        return prev
    try:
        data = _read(path)
    except (subprocess.SubprocessError, OSError):
        return {"e": {}, "read_failed": True}

    entries: Dict[str, list] = {}
    limits: Optional[list] = None  # [epoch, rate_limits]
    model = ""
    legacy = {}
    reported_totals = set()
    preceding_usage = None
    restored_history = False
    prev_total = -1
    for n, raw in enumerate(data.splitlines()):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        kind = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if kind in ("session_meta", "turn_context"):
            if isinstance(payload.get("model"), str):
                model = payload["model"] or model
        elif kind == "compacted" and prev_total < 0 and not entries:
            restored_history = True
        elif kind == "token_usage_record":
            ts = _epoch(rec.get("timestamp", ""))
            usage = payload.get("usage") or {}
            if ts is None or not isinstance(usage, dict) or not usage:
                continue
            key = payload.get("response_id") or f"{payload.get('thread_id') or path.name.removesuffix('.zst')}:{rec.get('ordinal', n)}"
            merge_request(entries, key, ts, request_cost(model or DEFAULT_MODEL, usage))
            thread_usage = payload.get("thread_token_usage")
            total = thread_usage.get("total_tokens") if isinstance(thread_usage, dict) else None
            signature = usage.get("total_tokens")
            if total is not None:
                reported_totals.add((total, signature))
            preceding_usage = (usage.get("input_tokens"), usage.get("output_tokens"), signature)
        elif kind == "event_msg" and payload.get("type") == "token_count":
            ts = _epoch(rec.get("timestamp", ""))
            if ts is None:
                continue
            rate_limits = payload.get("rate_limits")
            if isinstance(rate_limits, dict) and rate_limits.get("limit_id") in (None, "codex"):
                if limits is None or ts >= limits[0]:
                    limits = [ts, rate_limits]
            info = payload.get("info") or {}
            if not isinstance(info, dict):
                continue
            usage = info.get("last_token_usage")
            cumulative = info.get("total_token_usage")
            total = cumulative.get("total_tokens") if isinstance(cumulative, dict) else None
            if isinstance(usage, dict) and isinstance(total, int) and total > prev_total:
                signature = usage.get("total_tokens")
                key = f"legacy:{rec['timestamp']}:{total}:{signature}"
                usage_signature = (usage.get("input_tokens"), usage.get("output_tokens"), signature)
                # Resumed compacted logs start with a snapshot of usage incurred before this file.
                baseline = restored_history and prev_total < 0 and isinstance(signature, int) and total > signature
                if not baseline and usage_signature != preceding_usage:
                    legacy[key] = (ts, total, signature, request_cost(model or DEFAULT_MODEL, usage))
                preceding_usage = None
            if isinstance(total, int):
                prev_total = total

    # Mixed-version and forked rollouts can carry both representations of a response.
    for key, (ts, total, signature, cost) in legacy.items():
        if (total, signature) not in reported_totals:
            entries[key] = [ts, cost]
    return {"m": st.st_mtime_ns, "s": st.st_size, "e": entries, "l": limits}


def _rollouts(home: Path):
    for folder in ("sessions", "archived_sessions"):
        base = home / folder
        if base.is_dir():
            yield from base.glob("**/rollout-*.jsonl")
            yield from base.glob("**/rollout-*.jsonl.zst")


def scan(home: Optional[Path] = None) -> Tuple[Dict[str, list], Optional[dict], bool]:
    """(requests {key: [epoch, cost]}, limits, some compressed rollouts couldn't be read)."""
    home = home or codex_home()
    files = cached_scan("codex-rollouts", CACHE_VERSION, home, _rollouts(home), _scan_file)
    latest = None
    for info in files.values():
        lim = info.get("l")
        if lim and (latest is None or lim[0] > latest[0]):
            latest = lim
    missing = any(info.get("read_failed") for info in files.values())
    return merge_entries(files), _normalise_limits(latest), missing


def _normalise_limits(latest: Optional[list]) -> Optional[dict]:
    if not latest:
        return None
    ts, rl = latest
    windows = []
    for name in ("primary", "secondary"):
        w = rl.get(name)
        if isinstance(w, dict) and isinstance(w.get("used_percent"), (int, float)):
            resets = w.get("resets_at")
            if resets is None and isinstance(w.get("resets_in_seconds"), (int, float)):  # older Codex versions
                resets = ts + int(w["resets_in_seconds"])
            windows.append({"minutes": w.get("window_minutes"), "used_percentage": w["used_percent"], "resets_at": resets})
    return {"updated_at": ts, "windows": windows, "plan": rl.get("plan_type")}


def account_limits(home: Path) -> Optional[dict]:
    """Read the signed-in account's Codex bucket through the CLI's JSON-RPC interface."""
    cli = shutil.which("codex", path=os.pathsep.join((
        os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin",
        "/Applications/Codex.app/Contents/Resources",
    )))
    try:
        if not cli or not home.is_dir():
            return None
        # Newline-delimited JSON-RPC is the standalone server's stdio transport.
        cmd = [cli, "app-server", "--listen", "stdio://"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, env={**os.environ, "CODEX_HOME": str(home)}) as proc:
            try:
                result = _read_account_rpc(proc)
            finally:
                if proc.poll() is None:
                    proc.kill()
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict):
        return None
    buckets = result.get("rateLimitsByLimitId") or {}
    if not isinstance(buckets, dict):
        return None
    bucket = buckets.get("codex") or result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        return None
    windows = []
    for name in ("primary", "secondary"):
        w = bucket.get(name)
        if isinstance(w, dict) and isinstance(w.get("usedPercent"), (int, float)):
            windows.append({"minutes": w.get("windowDurationMins"), "used_percentage": w["usedPercent"],
                            "resets_at": w.get("resetsAt")})
    if not windows:
        return None
    return {"updated_at": int(time.time()), "windows": windows, "plan": bucket.get("planType"),
            "source": "account"}


def _read_account_rpc(proc: subprocess.Popen) -> Optional[dict]:
    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        proc.stdin.flush()

    send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "alfred_usage", "version": "1"}}})
    deadline = time.monotonic() + 8
    pending = b""
    while time.monotonic() < deadline:
        if not select.select([proc.stdout], [], [], max(0, deadline - time.monotonic()))[0]:
            break
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            break
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            reply = json.loads(line)
            if not isinstance(reply, dict):
                continue
            if reply.get("id") == 1:
                if "error" in reply:
                    return None
                send({"method": "initialized"})
                send({"id": 2, "method": "account/rateLimits/read", "params": {"excludeResetCreditDetails": True}})
            elif reply.get("id") == 2:
                return reply.get("result")
    return None
