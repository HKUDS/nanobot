# 概念

当你想在更改高级设置前了解 nanobot 时，请使用本页。它解释了各个组成部分，无需你先阅读源代码。

如果你想了解源文件归属和扩展点，请在阅读本页后查看 [`architecture.md`](architecture-zh.md)。

## 运行时结构

nanobot 有一个小型核心循环，以及几种进入该循环的方式：

| 部分 | 作用 |
|---|---|
| Agent 循环 | 构建上下文、选择 session、调用 provider、运行 tool 并发布回复 |
| Providers | LLM 后端，例如 OpenRouter、Anthropic、OpenAI、Bedrock、Ollama、vLLM，以及其他兼容 OpenAI 的 API |
| Channels | 面向用户的传输方式，例如 CLI、WebUI/WebSocket、Telegram、Discord、Slack、Feishu、WeChat、Email、Mattermost 等 |
| Tools | model 可调用的能力，包括文件、shell、网页搜索/抓取、MCP、cron、图像生成和 subagent |
| Memory | workspace 文件和 session 历史，用于在多轮之间保留有用的上下文 |
| Gateway | 连接已启用 channel 并提供健康检查端点的长期运行进程 |

最简单的路径是 `nanobot agent -m "Hello!"`：一条入站消息经过 Agent 循环，并将回复输出到你的终端。长期运行的路径是 `nanobot gateway`：channel 从聊天应用或 WebUI 接收消息，将其发布到同一个 Agent 循环，然后把回复发送回原始 channel。

## Config 与 Workspace

默认实例位于 `~/.nanobot/` 下：

| 路径 | 含义 |
|---|---|
| `~/.nanobot/config.json` | 实例配置：provider、model 默认值、channel、tool、gateway、API 和运行时选项 |
| `~/.nanobot/workspace/` | Agent workspace：memory、session、heartbeat 任务、cron 作业、skill 和生成的产物 |

你可以使用命令标志覆盖两者：

```bash
nanobot onboard --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
```

config 文件控制 nanobot 可以使用什么。workspace 是 nanobot 为该实例保存状态的位置。

### Agent Workspace 与 Project Workspace

已配置的 workspace 是 **agent workspace**。WebUI 聊天也可以选择不同的 **project workspace** 来进行特定于仓库的工作，而无需迁移 Agent 的身份或持久状态。

| 资源 | 选择 project 后的所有者 |
|---|---|
| 项目指令 | 所选 project 中的 `AGENTS.md`；不会回退到 agent workspace 的 `AGENTS.md` |
| Agent 配置文件 | agent workspace 中的 `SOUL.md` 和 `USER.md`；会忽略 project 本地同名文件 |
| Memory 和自定义 skill | agent workspace 中的 `memory/` 和 `skills/` |
| 相对文件路径和 shell 工作目录 | 所选 project workspace |

未选择单独的 project 时，一个目录通常同时承担这两种角色。选择 project 会更改该聊天的工作上下文；不会创建第二个 Agent，也不会迁移已配置的 agent workspace。

## Config 格式

`config.json` 同时接受 camelCase 和 snake_case key。文档使用 camelCase，因为 nanobot 会使用 camelCase 别名将 config 写回磁盘，例如 `apiKey`、`modelPresets`、`intervalS` 和 `maxToolResultChars`。

大多数示例都是局部片段。请将它们合并到由 `nanobot onboard` 创建的现有文件中；除非你想重置实例，否则不要替换整个文件。

## 一次 Agent 轮次

一次正常轮次遵循以下流程：

1. 一个 channel 接收用户消息并将其发布到消息总线。
2. Agent 循环选择 session key，并根据有效的 project workspace、Agent 所有的配置文件/skill/memory、最近消息、channel 元数据和运行时设置构建上下文。
3. provider 接收 model 请求。
4. 如果 model 请求使用 tool，runner 会执行它们并将结果反馈给 model。
5. 最终回复会保存到 session，并通过 channel 发回。

无论消息始于 CLI、WebUI、Telegram、Discord 还是其他 channel，该流程都相同。

## CLI、Gateway、API 和 WebUI

| 入口点 | 命令 | 用途 |
|---|---|---|
| CLI 单次执行 | `nanobot agent -m "..."` | 首次运行检查、脚本和快速本地提问 |
| CLI 交互模式 | `nanobot agent` | 带有持久 session 历史的终端聊天 |
| Gateway | `nanobot gateway` | 聊天应用、WebUI、heartbeat、Dream 和长期运行的服务模式 |
| 兼容 OpenAI 的 API | `nanobot serve` | 通过 `/v1/chat/completions` 进行编程访问 |
| WebUI | `nanobot webui` | 准备本地 WebUI、启动 gateway，并打开浏览器工作台 |

WebUI 启动器是常规的浏览器入口点。底层的 gateway 会保持 WebSocket channel 和其他长期运行服务处于活动状态。gateway 健康检查端点位于 `gateway.port`（默认是 `18790`）；浏览器 WebUI 默认通过 `8765` 提供服务，而不是由健康检查端点提供。

## Provider 和 Model 选择

活动 model 通常应来自由 `agents.defaults.modelPreset` 选定的命名 `modelPresets` 条目。直接使用的 `agents.defaults.provider` 和 `agents.defaults.model` 仍会为旧版或最简 config 构成隐式 `default` preset。活动 provider 按以下顺序解析：

1. 如果活动 preset provider 或隐式 default provider 不是 `"auto"`，nanobot 使用该 provider。
2. 如果 provider 是 `"auto"`，nanobot 会尝试根据 model 名称、已配置的 API key、本地 provider base URL 或 gateway provider 推断 provider。
3. OpenAI Codex 和 GitHub Copilot 等 OAuth provider 需要在活动 preset 中显式登录，并显式选择 provider/model。

首次设置时，请在 preset 内固定 provider。这更容易调试：

```json
{
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

实用示例请参阅 [`providers.md`](providers-zh.md)，完整 provider 参考请参阅 [`configuration.md#providers`](configuration-zh.md#providers)。

## Channels 和 Sessions

每个 channel 都会将入站消息映射到一个 session key。这使独立对话能够保留各自独立的历史记录。WebUI 还支持多个聊天和面向 project workspace 的元数据。

`agents.defaults.unifiedSession` 可以有意地让多个 channel 共享一个 session，适用于单用户多设备设置。如果你希望不同人员、群组、channel 或 project 保持独立上下文，请将其关闭。

## Memory、Sessions 和 Dream

nanobot 使用两个相关的存储：

| 存储 | 位置 | 用途 |
|---|---|---|
| Sessions | `<workspace>/sessions/*.jsonl` | 重放到上下文中的最近对话轮次 |
| Memory | `<workspace>/memory/MEMORY.md` 和 `<workspace>/memory/history.jsonl` | 长期事实和汇总后的历史 |

Dream 是一个定期整合作业。它读取积累的历史，并更新 workspace memory，使有用的上下文能够超越短期 session 重放而保留下来。

详细设计请参阅 [`memory.md`](memory-zh.md)。

## Tools 和安全性

tool 会从内置模块和 plugin 入口点自动发现。常见的 tool 组包括：

- 文件读取/写入/编辑和补丁；
- 使用可配置沙箱的 shell 执行；
- 具备 SSRF 检查的网页搜索和网页抓取；
- MCP server；
- cron 提醒、本地 trigger 和 heartbeat 任务；
- 图像生成；
- subagent 和运行时自检。

安全敏感控制项位于 [`configuration.md#security`](configuration-zh.md#security)。对于生产环境或共享聊天应用，还应配置 channel 访问控制，例如 `allowFrom`、配对或 WebSocket token。

## 后台作业

当 `nanobot gateway` 启动时，它会运行以 workspace 为作用域的自动化操作，并注册系统作业：

- 当 `agents.defaults.dream.enabled` 为 true 时，运行 `dream`；
- 当 `gateway.heartbeat.enabled` 为 true 时，运行 `heartbeat`。

Heartbeat 会读取 `<workspace>/HEARTBEAT.md`。如果该文件在 `## Active Tasks` 下包含任务，nanobot 会执行它们，并且只将有用且可操作的结果发送给最近活跃的聊天目标。常规的“没有变化”结果会被抑制。

用户创建的提醒使用相同的 cron 服务，但不同于受保护的 heartbeat 系统作业。它们会作为源聊天/session 中的计划轮次运行，并且通常将结果发回该 channel。

本地 trigger 也与 session 绑定，但没有自己的计划。请从目标聊天使用 `/trigger <name>` 创建一个，然后当本地脚本或外部服务希望 nanobot 在该 session 中响应时，调用 `nanobot trigger <id> "<message>"`。Webhook server、第三方认证和事件到消息的格式化均保留在 nanobot 外部。trigger 投递会存储在 workspace 中，直到关联的 Agent 轮次成功完成。如果目标 session 正忙，trigger 会等待该 session 空闲，而不会注入正在进行的轮次。该消息会作为该 session 中的自动化轮次被记录。投递语义为至少一次，因此外部系统应能容忍重复的 trigger 消息；已到达 Agent 但失败的投递会被标记为失败，而不会无限重试。

## 下一步

| 需求 | 阅读 |
|---|---|
| 首次可用安装 | [`quick-start.md`](quick-start-zh.md) |
| Provider/model 设置 | [`providers.md`](providers-zh.md) |
| 聊天应用设置 | [`chat-apps.md`](chat-apps-zh.md) |
| 完整 config 参考 | [`configuration.md`](configuration-zh.md) |
| 运行时调试 | [`troubleshooting.md`](troubleshooting-zh.md) |
