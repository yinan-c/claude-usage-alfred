# Claude Usage for Alfred

[English](README.md) · **简体中文**

在 Alfred 中输入 `usage`，即可查看 Claude Code 和 Codex 的额度使用率、重置时间，以及最近 13 周的活动热力图。工作流还会根据本机记录的请求，按 API 公开价格估算费用。

[下载 Alfred 工作流](https://github.com/yinan-c/claude-usage-alfred/releases/download/v1.1.0-rc.1/Claude-Usage.alfredworkflow) · [查看发布说明](https://github.com/yinan-c/claude-usage-alfred/releases/tag/v1.1.0-rc.1)

## 安装并打开

1. 在装有 Alfred 并已激活 Powerpack 的 Mac 上，从发布页的 **Assets** 下载 **Claude-Usage.alfredworkflow**。
2. 双击文件，在 Alfred 中选择 **Import**。如果已经安装过，选择 Alfred 提供的更新选项。
3. 唤出 Alfred，输入 `usage` 并按回车。点击标签即可查看对应服务。也可以输入 `usage codex` 或 `usage claude`，直接进入指定标签。

工作流使用系统的 `/usr/bin/python3`。如果 macOS 提示缺少 Command Line Tools，请在终端运行 `xcode-select --install`，安装完成后重新打开工作流。Codex 的普通会话日志可直接读取；如果还有 `.jsonl.zst` 压缩日志，运行 `brew install zstd` 即可将它们计入统计。

## 使用面板

| 操作 | 功能 |
| --- | --- |
| 点击标签或按 Tab | 在已启用的服务之间切换，用量数据在后台加载 |
| ⌘1 或 ⌘2 | 选择从左到右的第一个或第二个标签 |
| 将鼠标悬停在热力图方格上 | 查看当天的估算费用和请求数 |
| ⌘R | 刷新当前服务。面板打开期间，已启用的服务也会每 30 秒自动刷新 |
| 回车 | 在浏览器中打开当前服务的官方用量页 |

在 **Alfred Preferences → Workflows → Claude Usage → Configure Workflow** 中可以更改唤起关键词和数据目录。**Show providers** 默认记住上次查看的标签，也可以固定两个标签的顺序，或只显示其中一个服务。

**额度怎么看？** 周额度显示 26%，表示服务方报告本周额度已用 26%。热力图记录本机命令行客户端的活动。如果 Codex 只返回周额度，面板就只显示周额度。额度重置后，面板会等到取得新读数再显示百分比。

**费用怎么算？** 面板分别统计本周（从周一开始）、本月和可选的订阅周期。按 `YYYY-MM-DD` 格式为每个服务填写周期开始日和续费日。例如，6 月 10 日至 7 月 10 日的周期统计到 7 月 9 日为止。金额后的 `+` 表示部分请求缺少价格，当前金额是已知价格的小计。将鼠标悬停在各项小计上可查看统计日期。

## 配置 Claude 额度

工作流从 `~/.claude/projects` 下的会话记录统计 Claude 活动。要显示账户额度，可任选以下方式。

- **通过已登录的命令行客户端查询。** 在 **Configure Workflow** 中启用 **Live account limits**，然后刷新。启用后，各服务的客户端可以连接自己的账户服务查询额度。如果客户端未返回额度，工作流会使用已有的本机读数。
- **通过 Claude Code 状态栏记录。** 如果希望沿用默认的本地读取方式，请安装一次随工作流提供的状态栏脚本。

  1. 在 Alfred Preferences 中右键点击 **Claude Usage**，选择 **Open in Finder**。找到 `statusline.py`，在该目录打开终端并运行以下命令。

     ```sh
     mkdir -p ~/.claude
     cp statusline.py ~/.claude/statusline-usage.py
     ```

  2. 打开 `~/.claude/settings.json`，将下面的 `statusLine` 属性加入现有 JSON 对象，保留其他设置。如果已有自定义状态栏，可通过 `CLAUDE_USAGE_STATUSLINE_CMD` 继续调用原命令。例如，将下方的 `command` 值改为 `CLAUDE_USAGE_STATUSLINE_CMD='my-status-command' /usr/bin/python3 ~/.claude/statusline-usage.py`，并用原命令替换 `my-status-command`。

     ```json
     {
       "statusLine": {
         "type": "command",
         "command": "/usr/bin/python3 ~/.claude/statusline-usage.py"
       }
     }
     ```

  3. 启动 Claude Code 会话并发送一条消息。状态栏收到额度数据后，会写入 `~/.claude/usage-limits.json`。在 Alfred 中输入 `usage claude` 打开面板，再按 ⌘R 刷新。

如果自定义了 Claude 配置目录，请将 **Claude config folder** 指向该目录，并相应调整脚本和设置文件的路径。Codex 的对应设置是 **Codex folder**，默认目录为 `~/.codex`，统计范围包括当前和已归档的会话。

## 数据与开发

关闭 **Live account limits** 时，工作流会读取本地会话文件，并将每个文件的统计结果存入 Alfred 的工作流缓存。面板中的费用按 API 价格估算，实际订阅账单可能不同。本项目由社区独立维护，与 Anthropic 和 OpenAI 均无隶属关系。

在仓库根目录运行回归测试：

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

Claude 和 Codex 的模型价格分别在 `usage.py` 和 `codex.py` 中维护。更改价格或日志解析逻辑时，请递增对应文件中的 `CACHE_VERSION`，以便重新计算已缓存的统计结果。

[MIT 许可证](LICENSE)
