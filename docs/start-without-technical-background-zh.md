# 无需技术背景即可开始

本演练面向此前未使用过终端、API key 或 JSON 配置文件的用户。目标只是让你在浏览器中获得一条回复。你无需了解 nanobot 的架构，也无需手动编辑其配置。

## 你需要准备的内容

- 一台 Windows、macOS 或 Linux 电脑。
- Python 3.11 或更新版本。
- 一个能够运行 AI model 的账户或 endpoint。
- 该服务所需的 API key、登录信息、endpoint 和 model 名称。本地 model（如 Ollama）可能不需要 API key。

API key 类似密码。不要将其发布在 issue、截图、聊天记录或公开配置文件中。

## 几个实用术语

| 术语 | 含义 |
|---|---|
| 终端 | 一个可粘贴 command 并按 Enter 的文本窗口 |
| Command | 在终端中输入的一条指令 |
| Provider | 运行 AI model 的服务或本地服务器 |
| Model ID | 该 provider 所要求的准确 model 名称 |
| API key | 允许软件调用 provider 的私密凭据 |
| 向导 | 问答式设置菜单 |
| WebUI | 你用来使用 nanobot 的本地浏览器页面 |

## 1. 安装 Python

如果你尚未安装 3.11 或更新版本，请从 [python.org](https://www.python.org/downloads/) 下载 Python。在 Windows 上，如果安装程序显示该选项，请启用 **Add python.exe to PATH**。

打开终端：

| 系统 | 操作方法 |
|---|---|
| Windows | 按 `Win`，输入 `PowerShell`，然后打开 Windows PowerShell |
| macOS | 按 `Command+Space`，输入 `Terminal`，然后按 Enter |
| Linux | 打开应用程序菜单并搜索 Terminal |

检查 Python：

```bash
python --version
```

结果应以 `Python 3.11` 或更高版本号开头。如果找不到该 command，请关闭并重新打开终端。在 macOS/Linux 上也可以尝试 `python3 --version`，在 Windows 上可以尝试 `py --version`。

## 2. 准备你的 Model 详情

nanobot 不会为你创建 AI provider 账户。开始设置前，请准备好以下信息：

1. provider 或公司 endpoint 名称。
2. 它的 API key（如果需要）。
3. 它的 base URL（如果其文档提供了）。
4. 你的账户可以使用的 model ID。

provider、credential、endpoint 和 model 必须相互对应。例如，一个 provider 的 API key 通常不能调用从其他 provider 复制来的 model 名称。

## 3. 安装 nanobot

复制适用于你系统的 command，将其粘贴到终端，然后按 Enter。仅复制代码块内的文本。

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

安装程序会将稳定版 nanobot package 下载到隔离的 Python environment 中。在全新的本地桌面环境中，它随后会启动 WebUI 并打开浏览器。首次运行可能需要几分钟。请保持终端开启。它会打印用于运行 nanobot 的准确 command；如果之后找不到 `nanobot`，请复用该完整 command，而不要切换到其他 Python command。

如果你的组织禁止下载的安装脚本，请使用[替代安装方法](quick-start-zh.md#other-install-methods)，或请管理员先审核这些脚本。

## 4. 在 WebUI 中配置你的 Model

在浏览器中打开 **Settings → Models**。然后：

1. 选择你的 provider。
2. 在需要时输入其 API key 和 base URL。
3. 创建或选择一个 model preset。
4. 输入你的 provider 账户可用的 model ID。
5. 保存配置。

请像对待密码一样对待每个 API key。不要在截图或支持请求中包含它。

如果安装程序完成后没有打开浏览器，并且 `nanobot` 可用，请运行：

```bash
nanobot webui
```

如果终端找不到 `nanobot`，请使用安装程序打印的准确 command，并将其最终参数替换为 `webui`。该 command 可能以 `uv tool run`、`pipx run` 或 nanobot 私有 Python environment 的完整路径开头。

在 SSH、没有桌面的电脑、已有配置或较旧的 nanobot release 中，安装程序可能会改为打开终端向导。请在其中选择 **Quick Start**，并按照提示操作。

## 5. 获取第一条回复

保持 WebUI 的终端开启。如果浏览器没有自动打开，请访问 `http://127.0.0.1:8765`。

发送以下消息：

```text
Hello!
```

收到正常的 assistant 回复即表示设置完成。具体回复内容并不重要。

首次运行时的地址仅在你的本地电脑上可用。它不会自动对网络中的其他电脑开放。

## 6. 一次只添加一项功能

不要立即配置所有功能。请选择一个下一步目标：

| 目标 | 操作方法 |
|---|---|
| 更改 AI model | 打开 **Settings → Models** |
| 添加 provider credential | 打开 **Settings → Models**，然后找到该 provider |
| 连接 Telegram、Discord、Slack、Feishu、WeChat 或其他聊天 app | 打开 **Settings → Channels**，选择平台，并按照其连接步骤操作 |
| 添加 tool integration | 打开 **Apps** 并选择一个 App 或 MCP integration |
| 安排提醒或重复任务 | 在目标聊天中询问 nanobot，然后在 **Automations** 中管理它 |
| 使用项目文件 | 开始新聊天，选择项目 workspace，并在发送任务前检查访问设置 |

仓库文档展示的是当前开发版本。如果你的稳定 package 尚未显示 **Settings → Channels**，请使用 [Chat Apps 指南](chat-apps-zh.md)，或更新到包含该功能的 release。

某些运行时更改会要求你重启 nanobot。请使用 WebUI 显示的重启操作，或返回终端，按 `Ctrl+C`，然后再次运行 `nanobot webui`。

有关聊天平台账户、bot、token 或权限的前置要求，请使用 [Chat Apps 指南](chat-apps-zh.md)。有关本地 model 和 provider 特定方案，请使用 [Provider Cookbook](provider-cookbook-zh.md)。

## 如果出现故障

请一次运行一条以下 command：

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| 你看到的内容 | 通常意味着什么 |
|---|---|
| `nanobot: command not found` | 复用安装程序打印的准确 nanobot command；它指向包含该 package 的隔离 environment |
| `401`、unauthorized 或 invalid API key | key 错误、已过期，或属于其他 provider |
| 未找到 Model | model ID 拼写错误，或你的 provider 账户无法使用该 model |
| 浏览器未打开 | 请自行打开 `http://127.0.0.1:8765`，并保持终端运行 |
| 浏览器打开但消息发送失败 | 测试 `nanobot agent -m "Hello!"`，以区分 model 问题和 WebUI 问题 |
| 已保存更改但没有任何变化 | 重启 nanobot，以便运行中的 process 重新加载 config |

如果你请求帮助，请提供你的操作系统、`nanobot --version`、`nanobot status`、准确 command 和准确错误信息。请先移除所有 API key、bot token、密码、OAuth token 和私有账户 ID。

请继续阅读完整的[故障排除指南](troubleshooting-zh.md)，按顺序进行诊断。

## 稍后打开 nanobot

运行：

```bash
nanobot webui
```

使用 nanobot 时请保持该终端开启。要停止它，请返回终端并按 `Ctrl+C`。仅在正常的前台启动和 model 设置正常工作后，才使用 `nanobot webui --background`；之后可通过 `nanobot gateway status`、`logs`、`restart` 和 `stop` 进行管理。
