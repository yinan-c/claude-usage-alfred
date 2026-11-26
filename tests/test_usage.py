"""Regression cases for tab routing, legacy rollouts and partial usage estimates."""
import json
import os
import runpy
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import usage
import codex

RENDER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "usage.alfredui/render"))


class UsageTests(unittest.TestCase):
    def test_native_switching_in_both_orders(self):
        def resolve(value, variables):
            if isinstance(value, str) and value.startswith("{var:"):
                return variables[value[5:-1]]
            return value

        build = RENDER["build"]
        for setting in ("codex_claude", "claude_codex"):
            with self.subTest(setting=setting), patch.dict(os.environ, usage_providers=setting):
                first, second = setting.split("_")
                with patch.dict(build.__globals__, safe_panel=self.fail):
                    initial = build("preload")
                state = initial["variables"]
                strip, stack = initial["replace"]["ids"]["providers"]["components"]
                pages = stack["components"]
                self.assertEqual([p["id"] for p in pages if not p["hidden"]], ["page_" + first])
                buttons = strip["components"]
                self.assertEqual([b["shortcut"] for b in buttons], ["⌘1", "⌘2"])
                shortcuts = {s["shortcut"]: s["action"] for s in initial["replace"]["ids"]["providers"]["shortcuts"]}
                self.assertEqual(set(shortcuts), {"⇥", "⌘R", "↩"})
                tab = shortcuts["⇥"]
                for action, expected in [(tab, second), (tab, first),
                                         (buttons[1]["events"][0]["action"], second), (tab, first)]:
                    self.assertEqual(action["type"], "json")
                    captured = {k: resolve(v, state) for k, v in action["variables"].items()}
                    result = action["src"]
                    state = {k: resolve(v, captured) for k, v in result["variables"].items()}
                    self.assertEqual(state["tool"], expected)
                    for provider in (first, second):
                        ids = result["update"]["ids"]
                        self.assertEqual(bool(resolve(ids["page_" + provider]["hidden"], captured)), provider != expected)
                        self.assertEqual(bool(resolve(ids["tab_" + provider]["bordered"], captured)), provider == expected)
                    self.assertEqual(build("open", state["tool"])["open"]["src"], RENDER["URLS"][expected])

    def test_keyword_and_last_viewed_tab(self):
        build = RENDER["build"]
        for setting, last, launch, expected in [
            ("remember", "codex", "", "codex"), ("remember", "claude", "codex", "codex"),
            ("claude_codex", "codex", "", "claude"), ("codex_claude", "codex", "claude", "claude"),
            ("claude", "codex", "codex", "claude"),
        ]:
            with patch.dict(os.environ, usage_providers=setting, tool=last, launch_tool=launch):
                self.assertEqual(build("preload")["variables"]["tool"], expected)

    def test_background_updates_only_replace_panel_content(self):
        build = RENDER["build"]
        auto_height = {"resize": {"height": "auto"}}
        with patch.dict(build.__globals__, safe_panel=lambda p: {"type": "label", "text": p}):
            for setting, order in RENDER["ORDERS"].items():
                with self.subTest(setting=setting), patch.dict(os.environ, usage_providers=setting):
                    pulse = build("pulse")
                    self.assertEqual(pulse, {"replace": {"ids": {
                        p: {"type": "label", "id": p, "text": p} for p in order}}, "window": auto_height})
                    for p in ("codex", "claude"):
                        expected = {"replace": {"ids": {p: {"type": "label", "id": p, "text": p}}},
                                    "window": auto_height}
                        for mode in ("load", "refresh"):
                            self.assertEqual(build(mode, p), expected if p in order else {})
                    if len(order) == 1:
                        view = build("preload")["replace"]["ids"]["providers"]
                        self.assertEqual({s["shortcut"] for s in view["shortcuts"]}, {"⌘R", "↩"})
                        self.assertEqual(len(view["components"]), 1)

    def test_offline_panels_use_upstream_limits_and_refit(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "claude_config_dir": temp, "codex_home": temp, "alfred_workflow_cache": temp,
            "usage_providers": "codex_claude", "live_limits": "0",
        }), patch.object(codex, "account_limits", side_effect=AssertionError), patch.object(
            usage, "account_limits", side_effect=AssertionError
        ):
            Path(temp, "usage-limits.json").write_text(json.dumps({"seven_day": {"used_percentage": 42}}))
            result = RENDER["build"]("pulse")
            self.assertEqual(result["window"], {"resize": {"height": "auto"}})
            for provider, panel in result["replace"]["ids"].items():
                self.assertEqual(panel["type"], "view")
                text = json.dumps(panel)
                self.assertIn(provider + "_weekUsage", text)
                if provider == "claude":
                    self.assertIn("Weekly: 42% used", text)
                    self.assertNotIn("5-hour session", text)

    def test_compacted_baseline_mixed_records_and_retry_after_read_error(self):
        def event(kind, payload, sec):
            return json.dumps({"type": kind, "timestamp": f"2026-11-01T00:00:{sec:02d}Z", "payload": payload})

        def count(last, total, sec):
            return event("event_msg", {"type": "token_count", "info": {
                "last_token_usage": {"total_tokens": last}, "total_token_usage": {"total_tokens": total}}}, sec)

        contents = "\n".join([event("compacted", {}, 0), count(20, 900, 1), count(11, 911, 2),
                              event("token_usage_record", {"response_id": "r", "usage": {"total_tokens": 10},
                                                           "thread_token_usage": {"total_tokens": 1950}}, 3),
                              count(10, 921, 5), "null", "{"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "rollout.jsonl")
            path.write_text(contents)
            with patch("codex._read", side_effect=OSError):
                failed = codex._scan_file(path, None)
            self.assertTrue(failed["read_failed"])
            entries = codex._scan_file(path, failed)["e"]
            self.assertEqual(len(entries), 2)
            self.assertIn("r", entries)

    def test_partial_price_and_expired_quota(self):
        today = date(2026, 11, 1)
        for unpriced, expected in [(0, "$2.00"), (1, "$2.00+"), (2, "Unpriced")]:
            days = {today: usage.DailyUsage(2, 2, unpriced)}
            self.assertTrue(RENDER["period_usage"](days, today, today)["text"].startswith(expected))
        rows = RENDER["limit_row"]({"minutes": 300, "used_percentage": 70, "resets_at": 5}, 10)
        self.assertEqual([v["type"] for v in rows], ["label"])
        self.assertNotIn("0% used", rows[0]["text"])

    def test_duplicate_cost_is_independent_of_file_order(self):
        for sequence in [[(12, None), (11, 4), (10, 2)], [(10, 2), (11, 4), (12, None)]]:
            entries = {}
            for ts, cost in sequence:
                codex.merge_request(entries, "r", ts, cost)
            self.assertEqual(entries["r"], [10, 4])
        self.assertEqual(usage.request_cost("claude-opus-5", {
            "cache_creation_input_tokens": 1000000, "cache_creation": {"ephemeral_1h_input_tokens": 1000000}}), 10)
        self.assertIsNone(codex.request_cost("codex-auto-review", {"input_tokens": 500}))


if __name__ == "__main__":
    unittest.main()
