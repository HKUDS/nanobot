# CLI 参考

当你知道要运行什么，但需要确认命令格式时，请使用此页面。若要按引导完成首次运行，请从 [`quick-start.md`](quick-start-zh.md) 开始。

## 选择命令

| 目标 | 命令 | 说明 |
|---|---|---|
| 检查安装 | `nanobot --version` | 如果失败，请尝试 `python -m nanobot --version` |
| 创建或刷新配置 | `nanobot onboard` | 创建 `~/.nanobot/config.json` 和 `~/.nanobot/workspace/` |
| 以非交互方式刷新配置 | `nanobot onboard --refresh` | 保留现有值，并在不提示的情况下添加缺失的默认字段 |
| 使用引导式设置 | `nanobot onboard --wizard` | 适合希望通过提示完成设置，而不是手动编辑 JSON 的情况 |
| 打开浏览器工作台 | `nanobot webui` | 准备本地 WebUI 设置，启动 gateway，并打开浏览器 |
| 检查就绪状态且不调用 model | `nanobot status` | 汇总配置/workspace，并验证活动 provider/model 配置 |
| 发送一条测试消息 | `nanobot agent -m "Hello!"` | 首次验证安装、配置、provider、model 和 workspace 是否正常工作 |
| 在终端中聊天 | `nanobot agent` | 交互式本地聊天；使用 `exit`、`/exit`、`:q` 或 `Ctrl+D` 退出 |
| 直接运行 gateway | `nanobot gateway` | 用于 WebUI、聊天应用、cron 和 heartbeat 的服务/运维命令 |
| 发送本地触发消息 | `nanobot trigger <id> "message"` | 首先在目标 chat/session 中使用 `/trigger <name>` 创建 |
| 提供兼容 OpenAI 的 API | `nanobot serve` | 启动 `/v1/chat/completions`、`/v1/models` 和 `/health` |
| 检查聊天 channel 设置 | `nanobot channels status` | 在启动 `nanobot gateway` 前很有用 |
| 管理可选功能 | `nanobot plugins list` | 显示可以启用的 channel 和可选功能 |
| 登录 QR/OAuth 风格的 channel | `nanobot channels login <channel>` | WhatsApp 和 WeChat 等 channel 使用此命令 |
| 登录 OAuth model provider | `nanobot provider login <provider>` | OpenAI Codex、xAI subscription 和 GitHub Copilot provider 使用此命令 |

## 全局选项

```bash
nanobot --help
nanobot --version
python -m nanobot --help
python -m nanobot --version
```

当软件包已安装但 `nanobot` 脚本不在 `PATH` 中时，`python -m nanobot ...` 很有用。

## 常见模式

大多数日常命令使用默认配置和 workspace。高级运行或多实例运行通常会显式传入两个路径：

```bash
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot serve --config ./bot-a/config.json --workspace ./bot-a/workspace
```

需要启动或运行时日志时，在长时间运行的进程中使用 `--verbose`：

```bash
nanobot gateway --verbose
nanobot serve --verbose
```

长时间运行的命令会持续工作，直到你停止它们。在相应终端中按 `Ctrl+C`
可停止前台运行的 `nanobot gateway` 或 `nanobot serve`。如果你使用
`--background` 启动了 gateway，请使用 `nanobot gateway stop`。

## 设置

| 命令 | 描述 |
|---|---|
| `nanobot onboard` | 初始化或刷新默认配置和 workspace |
| `nanobot onboard --refresh` | 在不提示的情况下刷新现有配置，并保留现有值 |
| `nanobot onboard --wizard` | 使用交互式设置向导 |
| `nanobot onboard --config <path> --workspace <path>` | 初始化或刷新指定实例 |

默认路径：

| 路径 | 默认值 |
|---|---|
| 配置 | `~/.nanobot/config.json` |
| Workspace | `~/.nanobot/workspace/` |

## 状态

| 命令 | 描述 |
|---|---|
| `nanobot status` | 汇总默认配置/workspace，并检查 Agent provider/model 是否就绪 |
| `nanobot status --config <path>` | 检查指定配置文件 |
| `nanobot status --workspace <path>` | 使用 workspace 覆盖值显示状态 |

status 不会发送 model 请求。成功后，运行输出的
`nanobot agent -m "Hello!"` 命令，以验证网络访问和凭据。失败时，
按照输出的 WebUI **Settings → Models** 或 `nanobot onboard --wizard` 路径操作。

## Agent CLI

| 命令 | 描述 |
|---|---|
| `nanobot agent -m "Hello!"` | 发送一条消息后退出 |
| `nanobot agent` | 启动交互式终端聊天 |
| `nanobot agent --session <id>` | 使用指定的 session key |
| `nanobot agent --workspace <path>` | 覆盖 workspace |
| `nanobot agent --config <path>` | 使用指定配置文件 |
| `nanobot agent --no-markdown` | 输出纯文本，而不是 Rich 渲染的 Markdown |
| `nanobot agent --logs` | 聊天时显示运行时日志 |

在交互模式下，按 `Enter` 发送当前消息。按 `Alt+Enter` 可在发送前添加换行。

交互模式可通过 `exit`、`quit`、`/exit`、`/quit`、`:q` 或 `Ctrl+D` 退出。

## WebUI

| 命令 | 描述 |
|---|---|
| `nanobot webui` | 如有需要则创建配置/workspace，在确认后启用本地 WebUI channel，启动 gateway，并打开 `http://127.0.0.1:8765` |
| `nanobot webui --background` | 启动或复用后台 gateway，然后打开 WebUI |
| `nanobot webui --dev` | 在 `http://127.0.0.1:5173` 同时启动 gateway 和 Vite，并实时更新前端 |
| `nanobot webui --no-open` | 准备并启动 WebUI，但不打开浏览器 |
| `nanobot webui --port <port>` | 设置 WebUI/WebSocket 端口 |
| `nanobot webui --gateway-port <port>` | 覆盖 gateway health 端口 |
| `nanobot webui --yes` | 无需确认即可应用安全的 localhost WebUI 默认值；在 **Settings → Models** 中配置 provider 凭据 |

首次运行的 WebUI 设置默认绑定到 `127.0.0.1`。在将 WebSocket channel 暴露到 localhost 之外之前，请使用手动配置和 WebUI 密码。

`--dev` 是前台源码检出工作流，不能与 `--background` 组合使用。
当 `webui/node_modules` 不存在时，它会安装前端依赖，将请求代理到已配置的
WebSocket channel 端口，并在前台 gateway 停止时一同停止 Vite。

## Gateway

`nanobot gateway` 会启动已启用的聊天 channel、配置后的 WebUI/WebSocket、由 cron
支持的系统任务、Dream、heartbeat 和 health endpoint。大多数本地浏览器用户应从
`nanobot webui` 开始；对于服务管理、聊天应用运行和高级部署，请直接使用
`gateway`。默认情况下，它在前台运行，从而保持现有脚本和终端工作流不变。如果希望运行
一个可通过 CLI 管理的本地 macOS、Linux 或 Windows 进程，请使用 `--background`。

| 命令 | 描述 |
|---|---|
| `nanobot gateway` | 使用配置默认值在前台启动 gateway |
| `nanobot gateway --verbose` | 显示详细运行时输出 |
| `nanobot gateway --port <port>` | 覆盖 health endpoint 使用的 `gateway.port` |
| `nanobot gateway --workspace <path>` | 覆盖 workspace |
| `nanobot gateway --config <path>` | 使用指定配置文件 |
| `nanobot gateway --background` | 将 gateway 作为后台进程启动 |
| `nanobot gateway status` | 显示已记录的后台 gateway PID、状态文件和日志文件 |
| `nanobot gateway logs --no-follow` | 输出最近的后台 gateway 日志后退出 |
| `nanobot gateway logs` | 跟踪后台 gateway 日志 |
| `nanobot gateway restart` | 使用当前配置重启已记录的后台 gateway |
| `nanobot gateway stop` | 停止已记录的后台 gateway |
| `nanobot gateway install-service` | 安装 systemd user service 或 macOS LaunchAgent |
| `nanobot gateway install-service --dry-run` | 预览生成的 service 文件和系统命令 |
| `nanobot gateway uninstall-service` | 删除已安装的系统 service |

对于自定义实例，将相同的选择器选项传递给管理命令：

```bash
nanobot gateway --background --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway status --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway stop --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway install-service --config ./bot-a/config.json --workspace ./bot-a/workspace --name bot-a
```

`--background` 是轻量级的分离进程。`install-service` 用于登录/启动集成：
Linux 使用 systemd user service；macOS 使用 LaunchAgent plist。系统 service 会在操作系统
supervisor 下运行前台 gateway，而不是再嵌套一个后台进程。

默认 health endpoint：

```text
http://127.0.0.1:18790/health
```

内置 WebUI 由 WebSocket channel 提供，通常使用端口 `8765`，而不是 gateway health endpoint。

## 本地触发器

`nanobot trigger` 向通过聊天/session 中的 `/trigger <name>` 创建的触发器发送一条本地消息。

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

保持 `nanobot gateway` 运行，以便将消息发送到关联的
聊天/session。该消息会作为该 session 中的一次自动化回合记录，
而不是作为用户输入的普通聊天消息记录。

该命令会写入 workspace 本地的持久队列。如果 `nanobot gateway`
尚未运行，消息会在该 workspace 中等待。如果目标 session 已经在运行某个回合，
触发器会等待该 session 变为空闲状态。如果 gateway 在认领投递后、关联回合完成前退出，
下一次 gateway 启动时会重新将该投递加入队列。该队列保证至少一次投递，而不是
恰好一次投递，因此中断的进程可能导致同一消息再次发送。如果 agent 收到该投递但回合失败，
该投递会标记为失败，而不会无限重试。每次投递还会在 `<workspace>/triggers/runs` 下
写入审计记录。每个 workspace 运行一个 gateway consumer；此本地队列不是分布式的
多 consumer 队列。

当另一个本地进程生成消息时，使用 stdin：

```bash
generate-report | nanobot trigger trg_8K4P2Q9X
```

选项：

| 命令 | 描述 |
|---|---|
| `nanobot trigger <id> "message"` | 通过触发器发送一条消息 |
| `nanobot trigger <id>` | 从 stdin 读取消息 |
| `nanobot trigger --config <path> <id> "message"` | 使用指定配置中的 workspace |
| `nanobot trigger --workspace <path> <id> "message"` | 使用指定 workspace |

触发器在 WebUI 的 Automations 视图中管理，而不是通过单独的
`list`、`revoke` 或 `delete` CLI 子命令管理。在那里可以暂停/恢复、
重命名、删除、搜索触发器，并复制每个触发器的命令。

对于 webhook 或其他外部系统，请运行自己的小型服务，并在确定 nanobot
应接收的消息后调用此 CLI。

参见 [Automations](automations-zh.md)，了解更广泛的自动化模型、WebUI
管理和投递行为。

## 兼容 OpenAI 的 API

| 命令 | 描述 |
|---|---|
| `nanobot serve` | 启动 `/v1/chat/completions`、`/v1/models` 和 `/health` |
| `nanobot serve --host <host>` | 覆盖 API 绑定主机 |
| `nanobot serve --port <port>` | 覆盖 API 端口 |
| `nanobot serve --timeout <seconds>` | 覆盖每次请求的超时时间 |
| `nanobot serve --verbose` | 显示运行时日志 |
| `nanobot serve --workspace <path>` | 覆盖 workspace |
| `nanobot serve --config <path>` | 使用指定配置文件 |

默认 API endpoint：

```text
http://127.0.0.1:8900
```

公开绑定（`0.0.0.0` 或 `::`）要求设置 `api.apiKey`；在 API 路由上将其作为 Bearer token 发送。

参见 [`openai-api.md`](openai-api-zh.md) 了解请求示例。

## 状态

```bash
nanobot status
```

显示配置路径、workspace 路径、活动 model 和 provider 摘要，但不会调用 model。

| 命令 | 描述 |
|---|---|
| `nanobot status` | 检查默认实例 |
| `nanobot status --config <path>` | 检查指定配置 |
| `nanobot status --config <path> --workspace <path>` | 在覆盖 workspace 的情况下检查指定配置 |
## Channels

| 命令 | 描述 |
|---|---|
| `nanobot channels status` | 显示已配置的 channel 状态 |
| `nanobot channels status --config <path>` | 显示指定 config 的 channel 状态 |
| `nanobot channels login <channel>` | 为受支持的 channel 运行交互式登录 |
| `nanobot channels login <channel> --force` | 即使凭据已存在，也重新进行身份验证 |
| `nanobot channels login <channel> --config <path>` | 使用指定的 config 文件 |
| `nanobot plugins list --config <path>` | 显示指定 config 的 plugin/channel 启用状态 |

示例：

```bash
nanobot channels login whatsapp
nanobot channels login weixin
nanobot channels status
```

有关特定 channel 的设置，请参阅 [`聊天应用`](chat-apps-zh.md)。

## 可选功能

当你希望 nanobot 添加或移除内置功能，而不想手动编辑 JSON 时，可以使用这些命令。启用功能可能会先安装支持包。禁用功能适用于 Telegram、Matrix 或 Slack 等 channel；它会保留已保存的设置，并关闭该 channel。

`plugins` 命令名称为保持兼容性而保留，但这些条目是 nanobot 运行时支持包，不是 WebUI Apps 中显示的可由用户调用的 tool。它们无法通过 `@` 附加到聊天轮次。

| 功能名称 | 启用的内容 |
|---|---|
| `api` | OpenAI 兼容的 `nanobot serve` 进程所需的依赖项 |
| `azure` | 对 Azure 托管 model 的 Azure 身份支持 |
| `bedrock` | AWS Bedrock model provider 支持 |
| `langfuse` | 对 OpenAI 兼容 provider 的 Langfuse 跟踪支持 |
| `olostep` | Olostep web 搜索 provider 支持 |
| 诸如 `telegram` 或 `slack` 的 channel 名称 | connector 包以及已保存的 channel 启用状态 |

| 命令 | 描述 |
|---|---|
| `nanobot plugins list` | 显示可用的 channel 和可选功能 |
| `nanobot plugins enable <name>` | 安装缺失的支持包并启用功能或 channel |
| `nanobot plugins enable <name> --logs` | 启用时显示包安装日志 |
| `nanobot plugins disable <channel>` | 关闭 channel，但不删除其已保存的设置 |
| `nanobot plugins list --config <path>` | 读取指定的 config 文件 |
| `nanobot plugins enable <name> --config <path>` | 更新指定的 config 文件 |
| `nanobot plugins disable <channel> --config <path>` | 在指定的 config 文件中关闭 channel |

文档和 PDF 阅读功能已包含在标准安装中。旧的 `nanobot plugins enable documents` 和 `nanobot plugins enable pdf` 命令仍会被接受，作为无操作的兼容性别名。

## Provider OAuth

| 命令 | 描述 |
|---|---|
| `nanobot provider login openai-codex --set-main` | 对 Codex 进行身份验证，并选择其当前默认 model |
| `nanobot provider login xai-grok --set-main` | 对符合条件的 X Premium / Grok 订阅进行身份验证，并选择 Grok 4.5；对于声明支持的 model，会启用托管的 X Search |
| `nanobot provider login github-copilot --set-main` | 对 GitHub Copilot 进行身份验证，并选择其当前默认 model |
| `nanobot provider logout openai-codex` | 移除 OpenAI Codex OAuth 状态 |
| `nanobot provider logout xai-grok --config <path>` | 移除所选 nanobot 实例的 xAI OAuth 状态 |
| `nanobot provider logout github-copilot` | 移除 GitHub Copilot OAuth 状态 |

有关 OAuth provider 何时需要显式选择 provider/model，请参阅 [`providers.md`](providers-zh.md#oauth-providers) 中的 OAuth provider 部分。

## 首要检查项

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

如果这些命令失败，请先使用 [`故障排除指南`](troubleshooting-zh.md)，然后再调试 WebUI、聊天应用、Docker、systemd 或 SDK 集成。
