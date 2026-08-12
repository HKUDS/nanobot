# 安装与快速开始

本指南只有一个目标：在浏览器中获得一条正常的 nanobot 回复。在这条路径正常工作之前，不要添加聊天应用、MCP 服务器、备用 model 或部署。

如果你不熟悉终端、Python 或 API 密钥，请使用[面向初学者的操作指南](start-without-technical-background-zh.md)，其中解释了每个术语和界面。

本仓库文档遵循当前的 `main`。推荐的安装程序使用稳定版软件包，因此新编写的 WebUI 界面可能要到下一个版本才会出现。每篇高级指南也提供 CLI 或手动配置路径。

## 你需要准备

- Python 3.11 或更高版本。
- 访问一个受支持的 AI provider、公司 endpoint 或本地 model 服务器。
- 该服务所需的凭据、endpoint URL 和 model ID。本地 provider（例如 Ollama）可能不需要密钥。

只有从源代码安装时才需要 Git。已发布的软件包已经包含 WebUI。安装当前源代码时需要 `bun` 或 `npm`，以便构建 WebUI bundle。

## 1. 安装 nanobot

推荐的安装程序不会将 nanobot 安装到系统 Python 环境中。在全新的本地桌面环境中，安装完成后它会启动 WebUI。

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

安装程序会选择活动的虚拟环境、`uv`、`pipx`，或 `~/.nanobot/venv` 下的托管环境。除非你明确传入 `--dev`，否则它会安装稳定的 PyPI 版本。最后，它会打印运行 nanobot 时使用的确切命令；如果 `nanobot` 不在 `PATH` 中，请在下面的示例中重复使用该完整命令。

如果你希望先检查脚本，请打开 [`install.sh`](../scripts/install.sh) 或 [`install.ps1`](../scripts/install.ps1)。

## 2. 配置你的 model

保持安装程序终端打开。浏览器会打开本地 WebUI；转到 **Settings → Models**，然后：

1. 选择拥有你的凭据的 provider 或 endpoint。
2. 在需要时输入其 API 密钥或基础 URL。
3. 使用该 provider 能够运行的 model ID 创建或选择一个 model preset。
4. 保存配置。

WebUI 启动器会创建或更新：

| 路径 | 用途 |
|---|---|
| `~/.nanobot/config.json` | provider、model、WebUI、channel、tool 和运行时设置 |
| `~/.nanobot/workspace/` | session、memory、技能、自动化任务和生成的文件 |

如果安装程序没有打开浏览器，请运行：

```bash
nanobot webui
```

SSH、无头环境、已有配置以及旧版本安装会保留终端设置路径：

```bash
nanobot onboard --wizard
```

## 3. 检查设置

```bash
nanobot status
```

你应看到：

- **Config** 和 **Workspace** 显示勾选标记；
- 你选择的 model 或 preset；
- 该 model 所使用的 provider 显示为已配置状态。

大多数其他 provider 可以显示为 `not set`。此命令会验证本地设置，但不会调用 model。

## 4. 获取第一条回复

如果安装程序启动的 WebUI 已不再运行，请再次运行 `nanobot webui`。保持该终端打开；首次运行的 WebUI 绑定到 localhost，因此网络中的其他设备无法访问它。

发送：

```text
Hello!
```

任何正常的 assistant 回复都表示成功。这证明 nanobot 能够加载配置、访问选定的 model、使用 workspace，并提供浏览器 UI。

使用 WebUI 时保持终端打开。如果你更喜欢使用托管的后台进程，请使用 `Ctrl+C` 停止前台进程，然后运行：

```bash
nanobot gateway --background
nanobot gateway status
```

使用 `nanobot gateway logs`、`restart` 和 `stop` 管理该后台 gateway。

## 仅使用终端检查

如果你不想使用浏览器，或需要隔离 WebUI 问题，请直接发送一条消息：

```bash
nanobot agent -m "Hello!"
```

然后使用以下命令启动交互式终端聊天：

```bash
nanobot agent
```

在交互模式下，`Enter` 发送消息，`Alt+Enter` 插入换行。使用 `exit`、`/exit`、`:q` 或 `Ctrl+D` 退出。

## 选择一个后续步骤

第一条回复正常后，添加一项能力并再次测试：

| 目标 | 推荐路径 |
|---|---|
| 了解 session、workspace、tool 和访问模式 | [WebUI 指南](webui-zh.md) |
| 连接聊天平台 | 打开 **Settings → Channels**，然后参阅[聊天应用](chat-apps-zh.md)了解平台前置条件 |
| 更改或添加 model | 打开 **Settings → Models**；参阅 [Provider Cookbook](provider-cookbook-zh.md)获取配置示例 |
| 添加网页搜索、语音或图像生成 | 使用对应的 WebUI Settings 页面，然后参阅[配置](configuration-zh.md)了解高级字段 |
| 添加 App 或 MCP 集成 | 打开 **Apps**，或按照[配置 MCP Tools](guides/configure-mcp-tools-zh.md)操作 |
| 安排 agent 工作 | 阅读[自动化任务](automations-zh.md) |
| 持续运行或远程运行 | 阅读[部署](deployment-zh.md) |
| 从代码进行集成 | 使用 [Python SDK](python-sdk-zh.md) 或 [OpenAI-Compatible API](openai-api-zh.md) |

## 其他安装方法

选择一种方法，然后继续阅读[配置你的 model](#2-configure-your-model)。

**uv**

```bash
uv tool install nanobot-ai
nanobot webui
```

**虚拟环境中的 pip**

```bash
python -m pip install nanobot-ai
nanobot webui
```

如果 pip 报告 `externally-managed-environment`，请使用推荐的安装程序、`uv tool install nanobot-ai`、`pipx install nanobot-ai`，或创建虚拟环境。不要强制执行系统范围安装。

**当前源代码**

必须有可用的 `bun` 或 `npm`。先激活虚拟环境，然后运行：

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install .
nanobot webui
```

在 Windows 上，如果 `python -m pip install .` 报告无法启动 `npm`，请依次运行 `cd webui`、`npm.cmd install --package-lock=false`、`npm.cmd run build` 和 `cd ..`，然后重试安装。

源代码路径遵循当前的 `main`，可能比已发布的软件包更新。不可编辑安装会触发构建钩子，以打包当前的 WebUI。对于可编辑的 Python 或前端开发，请遵循 [`../CONTRIBUTING.md`](../CONTRIBUTING.md) 和 [`../webui/README.md`](../webui/README.md)。

如果软件包已安装，但 shell 找不到 `nanobot`，请使用负责该安装的运行器。推荐的安装程序会打印要重复使用的确切命令。常见形式包括：

```bash
uv tool run --from nanobot-ai nanobot --version
pipx run --spec nanobot-ai nanobot --version
~/.nanobot/venv/bin/python -m nanobot --version
```

在 Windows 上，托管环境形式为 `& "$HOME\.nanobot\venv\Scripts\python.exe" -m nanobot --version`。将 `--version` 替换为 `webui`、`onboard --wizard` 或你需要的其他参数。只有在该 Python 可执行文件属于安装 nanobot 的环境时，才使用普通的 `python -m nanobot`。

## 手动配置备用方案

仅当向导不可用，或你有意管理 JSON 时使用此方法。先运行 `nanobot onboard`，然后将一个 provider 和一个命名的 model preset 合并到 `~/.nanobot/config.json` 中。

通用的 OpenAI-compatible 设置形式如下：

```json
{
  "providers": {
    "custom": {
      "apiKey": "${PROVIDER_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "custom",
      "model": "model-id-from-your-provider"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

请同时替换 provider、endpoint 和 model。不要将一个服务的凭据与另一个服务的 model ID 配对。有关托管、OAuth、公司和本地示例，请参阅 [Provider Cookbook](provider-cookbook-zh.md)；有关确切字段，请参阅[配置](configuration-zh.md)。

## 更新

使用安装时采用的相同方法升级：

```bash
# 推荐的安装程序
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh

# 或以下方法之一
uv tool upgrade nanobot-ai
pipx upgrade nanobot-ai
python -m pip install -U nanobot-ai
```

对于源代码检出：

```bash
git pull
python -m pip install .
```

然后检查 `nanobot --version`。当你希望添加新引入的默认字段，同时保留现有设置时，运行 `nanobot onboard --refresh`。

## 如果第一条回复失败

不要一次更改多个设置。先运行：

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| 症状 | 首先检查 |
|---|---|
| `nanobot: command not found` | 重复使用[其他安装方法](#other-install-methods)中介绍的安装程序命令或特定方法运行器 |
| JSON 解析错误 | 检查逗号和大括号；记住，文档示例通常只是代码片段 |
| `401` 或 API 密钥无效 | 确认选定的 provider 拥有该密钥，并删除意外的空格 |
| 找不到 model | 使用活动 preset 中所选 provider 提供的 model ID |
| CLI 可以运行，但 WebUI 无法打开 | 使用端口 `8765`，不要使用 gateway 健康检查端口 `18790` |
| WebUI 可以运行，但聊天应用无法运行 | 检查 **Settings → Channels**，然后运行 `nanobot channels status` |

如果原因仍不明确，请继续阅读有序的[故障排除指南](troubleshooting-zh.md)。
