# Claude Usage for Alfred

**English** · [简体中文](README.zh-CN.md)

Open Alfred and type `usage` to see Claude Code and Codex plan limits, reset times, and 13 weeks of activity. The panel also estimates what your locally recorded requests would cost at API list prices.

[Download the Alfred workflow](https://github.com/yinan-c/claude-usage-alfred/releases/download/v1.1.0-rc.1/Claude-Usage.alfredworkflow) · [Release notes](https://github.com/yinan-c/claude-usage-alfred/releases/tag/v1.1.0-rc.1)

## Install and open

1. On a Mac with Alfred and the Powerpack, download **Claude-Usage.alfredworkflow** from the release assets.
2. Double-click the file and choose **Import** in Alfred. If Alfred already has this workflow, choose the update option it offers.
3. Open Alfred, type `usage`, and press Return. Select a tab to see that provider’s data. To open Codex directly next time, type `usage codex`. For Claude Code, use `usage claude`.

The workflow uses `/usr/bin/python3`. If macOS prompts for Command Line Tools, run `xcode-select --install` and reopen the workflow after installation. Codex reads plain session logs immediately. For compressed `.jsonl.zst` logs, install `zstd` with `brew install zstd`.

## Use the panel

| Action | Result |
| --- | --- |
| Click a tab or press Tab | Switch between enabled providers while data loads in the background |
| ⌘1 or ⌘2 | Select the first or second visible tab |
| Hover over a heatmap square | See that day’s estimated cost and request count |
| ⌘R | Refresh the current provider. Enabled providers also refresh every 30 seconds while the panel is open |
| Return | Open the selected provider’s account usage page |

Open **Alfred Preferences → Workflows → Claude Usage → Configure Workflow** to change the keyword, data folders or **Show providers**. The default reopens the last viewed tab. You can also choose a fixed order or show just one provider.

**Quota and activity measure different things.** A weekly bar at 26% means the provider reported 26% of that quota used. The heatmap counts local CLI activity. If Codex reports only a weekly window, the panel shows only that window. After a reset, the panel waits for a new reading before showing a percentage.

**Cost estimates** cover the current week (from Monday), calendar month and optional subscription cycle. Enter the cycle start and renewal dates for each provider in `YYYY-MM-DD` format. For example, June 10 to July 10 includes June 10 through July 9. A `+` after a dollar amount means some requests have no known price. Hover over a period total for the covered dates.

## Set up Claude quota readings

Local Claude activity appears from transcripts in `~/.claude/projects`. For quota readings, choose either method below.

- **Use the signed-in CLI.** Enable **Live account limits** in Configure Workflow and refresh. This setting allows each enabled provider’s CLI to contact its account service. If the CLI cannot return limits, the workflow uses available local readings.
- **Use the Claude status line.** To collect readings locally with the default settings, install the included status line script once:

  1. In Alfred Preferences, right-click **Claude Usage** and choose **Open in Finder**. In that folder, locate `statusline.py`. From a terminal opened in the same folder, run:

     ```sh
     mkdir -p ~/.claude
     cp statusline.py ~/.claude/statusline-usage.py
     ```

  2. In `~/.claude/settings.json`, add the following property to the existing JSON object. Keep your other settings. If you already use a custom status line, set `CLAUDE_USAGE_STATUSLINE_CMD` in the command to chain it, for example `CLAUDE_USAGE_STATUSLINE_CMD='my-status-command' /usr/bin/python3 ~/.claude/statusline-usage.py`.

     ```json
     {
       "statusLine": {
         "type": "command",
         "command": "/usr/bin/python3 ~/.claude/statusline-usage.py"
       }
     }
     ```

  3. Start a Claude Code session and send a message. When the status line receives quota data, it saves the reading in `~/.claude/usage-limits.json`. Open `usage claude` in Alfred and press ⌘R.

If you use a custom Claude configuration directory, set **Claude config folder** to that location and adjust the script and settings paths accordingly. The Codex equivalent is **Codex folder**, which defaults to `~/.codex` and includes both active and archived sessions.

## Data and development

With live limits off, the workflow reads local session files and caches per-file totals in Alfred’s workflow cache. The panel shows API-equivalent costs; your subscription invoice may differ. This is an independent project, unaffiliated with Anthropic and OpenAI.

To run the regression tests from a checkout:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

Model rates are in `usage.py` and `codex.py`. Bump the corresponding `CACHE_VERSION` when changing prices or parsing so cached totals are recomputed.

[MIT License](LICENSE)
