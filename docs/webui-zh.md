# Nanobot WebUI：用于自托管 AI Agents 的浏览器工作台

<!-- Meta description: 通过具有持久主题、可见 tool 活动、workspace 控制、Apps、MCP 预设、Skills、设置和 Automations 的浏览器 WebUI 运行 nanobot。 -->

WebUI 是 nanobot 的浏览器工作台，可在一个位置管理持久主题、可见的
agent 活动、workspace 控制、Apps、Skills、设置和 Automations。

已发布的 `nanobot-ai` wheel 已包含 WebUI bundle。只有在修改 frontend
本身时，才需要 `webui/` source directory。

## 打开 WebUI

使用启动器：

```bash
nanobot webui
```

`nanobot webui` 会在需要时创建 config/workspace，在确认后启用本地
WebSocket channel，在缺少时生成 WebUI bootstrap secret，启动 gateway 并打开浏览器。
使用全新的 config 时，它可以在尚未配置 model 前打开，让你在 **设置
→ Models** 中完成设置。首次运行流程默认将 WebUI 绑定到 `127.0.0.1`，因此
LAN 中的其他设备无法访问。

当你不想保持终端打开时，可在后台运行：

```bash
nanobot webui --background
```

在使用 `--background` 前，请先在前台 `nanobot webui` session 中完成首次
model 设置。

使用 `nanobot gateway status`、`nanobot gateway
logs`、`nanobot gateway restart` 和 `nanobot gateway stop` 管理后台 gateway。

手动 config 仍然可用。同一台机器上的 localhost WebUI 访问可以不使用浏览器密码。
当你有意将 WebUI 暴露到 localhost 之外，或希望使用浏览器密码时，请设置
`tokenIssueSecret`：

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true
    }
  }
}
```

WebUI 默认由端口 `8765` 上的 WebSocket channel 提供服务。默认端口为
`18790` 的 gateway health endpoint 不是浏览器 UI。

## 前 10 分钟

将 WebUI 用作主要设置界面：

1. 打开 **设置 → Models**，配置 provider、credential 和活动 model preset。
2. 在新主题中发送 `Hello!`，验证所选 model 能正常工作。
3. 开始项目工作前创建单独的主题，然后选择预期的 workspace 和 access mode。
4. 接下来只添加一项 capability：在 **设置 → Channels** 中添加 chat channel、在 **设置** 中添加 web/voice/image provider，或在 **Apps** 中添加 App/MCP integration。
5. 当 WebUI 显示需要重启时进行重启，然后使用尽可能小的请求测试该 capability。

此流程避免在常规设置中手动编辑 `config.json`。当你需要 WebUI 未公开的选项，
或者以 code 方式管理 config 时，请使用参考文档。

## 用途

| 区域 | 用途 |
|---|---|
| 主题 | 启动、切换、搜索、fork 和删除浏览器主题 |
| Agent 活动 | 在上下文中查看 thinking、tool calls、带 diff 的文件编辑、command 输出和生成的 artifacts |
| Workspace | 在请求文件或 shell 工作前选择项目 workspace |
| Access | 为 gateway configuration 允许的本地 capabilities 选择 access mode |
| Composer | 发送文本、图像、voice input、slash commands，以及用于主题、Apps 或 MCP presets 的 `@` mentions |
| Channels | 连接和验证 chat platforms，安装其可选支持，并管理已保存的 channel 设置 |
| Apps | 安装、测试、更新和使用本地 CLI App adapters 与 MCP presets |
| Skills | 在依赖它们之前检查可用的内置和 workspace Skills |
| Automations | 查看、搜索、运行、暂停、编辑和删除计划任务及本地触发的 agent turns |
| 设置 | 调整 models、providers、图像生成、voice、web tools、runtime 和安全选项 |

## 主题 Workspace

侧边栏是主题切换器。每个主题都保留自己的历史、标题、workspace 选择和关联的
automations。当你需要独立的上下文时使用新主题；当你想从现有位置继续但不改变
原始线程时使用 fork。

消息时间线同时显示用户可见的回复和 agent 活动。需要详细信息时，可以展开较长的
tool 或 reasoning 区段。

当 agent 写入或编辑文件时，活动项会显示目标路径、状态、变更行数，以及可用时的
unified diff。使用 **查看 diff** 展开变更；较大的 diff 可能会隐藏未变更的行，
或截断 inline preview。通过文件编辑中的 **打开文件**，可打开只读文件 preview panel。

文件 previews 遵循活动 session access mode。Restricted workspace access
只会 preview 所选 workspace 下的文件。当 gateway 允许该 access mode 时，
Full Access 可以 preview workspace 外的文件。

## Workspace 和 Access

开始特定于项目的工作前，请使用 workspace picker。这会为 agent 提供文件路径、
shell commands 和 session metadata 所需的正确项目上下文。

选择项目不会替换已配置的 agent workspace。这两个路径承担不同职责：

| 所选项目提供 | Agent workspace 继续提供 |
|---|---|
| 项目 `AGENTS.md` | `SOUL.md` 和 `USER.md` |
| 相对文件路径和 shell working directory | 长期 memory 和 history |
| Restricted mode 中正常的 read/write boundary | 自定义 Skills 和 instance state |

项目本地的 `SOUL.md` 和 `USER.md` 文件会被忽略，agent workspace 的
`AGENTS.md` 不会被单独选定的项目继承。当所选项目就是已配置的 agent workspace
时，这两种职责自然使用相同的 directory。

composer 中的 access control 控制 chat 的本地 capability 级别。它不会绕过你的
gateway、provider、shell sandbox 或 operating system configuration；它只会在当前
主题已经可用的 capabilities 中进行选择。

在 Restricted mode 中，普通文件和 shell 工作会保持在所选项目内。为保持 agent
连续性，filesystem/search tools 会获得对内置 Skills、agent workspace 中 custom
Skills 以及精确的 agent `memory/history.jsonl` 文件的有限只读访问权限。这不会
授予对相邻 memory 或 profile 文件的访问权限，也不允许在所选项目外写入。这些
tool exceptions 不会扩大浏览器的文件 preview boundary。

远程 WebUI connections 可能会降低当前 workspace 的 access。选择不同 workspace
或启用 Full Access 仍仅限于本地和 native clients。

## Composer

composer 支持纯文本消息、图像附件、在已配置 transcription 时的 voice input、
slash commands，以及已安装 Apps 或 MCP presets 的 `@` mentions。从 `@` 菜单中选择
其他主题以附加稳定 reference；恰好以 `@` 开头的纯文本不会附加历史记录。
Restricted chats 提供同一项目中的主题，而 Full Access chats 可以 reference 任意
WebUI 主题。Nanobot 仅在其历史相关时读取被 reference 的主题，并可在回复中链接它。
model badge 显示当前 model 或 preset，并在设置不完整时链接回 model 设置。

对于图像生成，请先配置 image provider，然后从 composer 使用 WebUI image mode。
有关 provider 设置和输出行为，请参阅 [`image-generation.md`](image-generation-zh.md)。

## Channels

打开 **设置 → Channels**，无需手动组装 JSON 即可连接 chat apps。搜索 platform，
打开其设置 panel，并按照该 channel 显示的字段或 QR 流程操作。引导式设置可以：

- 当 WebUI 在本地运行时安装缺失的可选 channel 支持；
- 收集 platform credentials，同时保留之前保存的值；
- 处理受支持的基于 QR 的登录流程；
- 验证连接并显示可操作的设置错误；
- 在 gateway 需要重启时通知你。

platform 本身可能仍要求你创建 bot、启用 event permissions、复制 token 或配置
webhook。有关这些 platform 侧的先决条件，以及手动 JSON/reference 选项，请使用
[`chat-apps.md`](chat-apps-zh.md)。

使用私有 DM 测试新 channel。当受支持的 channel 发送 pairing code 时，WebUI 会显示
待处理请求，以便你批准发送者。请保持 access 范围狭窄；除非有意开放公开访问，
否则不要使用 wildcard allowlist。

## Apps

从侧边栏打开 Apps，管理 nanobot 可以附加到 chat
turn 的 tools。默认的 **Ready** 视图只显示可立即使用的 tools：

- **Apps** 是 nanobot 在你的机器上运行的本地 command-line adapters。
  安装 adapter 不会修改其连接的 native desktop 或 web app。
- **Integrations** 是 MCP servers。Presets 提供已知 configurations，而
  custom integration panel 接受 stdio、HTTP 和 SSE servers。

Apps 有意不列出诸如 `api` 或 `bedrock` 的 nanobot runtime support packages。
这些 packages 用于启用 providers、servers 或 channels；它们不是可通过 `@`
附加到 turn 的 tools。请从 **System**、**Models** 或 **Web** 管理它们。PDF 和常见
Office document readers 已包含在 nanobot 中，并会在附加文件时自动激活。可选
integrations 的等效 CLI 仍为 `nanobot plugins`。请参阅
[`cli-reference.md`](cli-reference-zh.md#optional-features)。

某些 MCP presets 会连接至托管的无密钥 endpoints。例如，Firecrawl preset 使用
Firecrawl 托管的 MCP endpoint 提供搜索、抓取、爬取和提取 tools，无需 API key。
这不会替代 nanobot 内置的 web search provider；当 turn 需要 Firecrawl 更丰富的
web data tools 时，请通过 `@` mention Firecrawl MCP preset。

Parallel Search preset 连接至免费的匿名 Parallel Search MCP endpoint，并公开
`web_search` 和 `web_fetch`，无需 API key。它是可选 integration，不能替代
nanobot 内置的 web search provider；当 turn 应使用它时，请 mention
`@parallel-search`。

App 或 integration 可用后，请在 composer 中通过 `@` mention 它，将该 tool
附加到下一条消息。

## Skills

Skills 视图显示 agent 可用的 skill instructions，包括内置 Skills 和
workspace 提供的 Skills。当你想知道 nanobot 是否已经具有适用于某项任务的专用
workflow，并且尚未要求它执行该任务时，请查看此视图。
## 自动化

自动化是在关联话题中稍后运行的 agent 回合。请从其应运行的话题或 channel 中创建它们，以便 nanobot 保留正确的目标上下文。自动化运行时，通常会将结果发送回该话题。

有关完整的自动化模型、创建流程、触发 CLI 用法和传递语义，请参阅 [`automations.md`](automations-zh.md)。

有两种面向用户的自动化类型：

- 计划自动化：由 agent 的 cron tool 创建，在指定时间、间隔或 cron 表达式时运行。
- 本地触发器：使用 `/trigger <name>` 创建，在你调用本地命令时运行，例如 `nanobot trigger trg_8K4P2Q9X "Review PR #4502"`。

对于应定期在后台检查、且仅在有有用信息可报告时才保持静默的任务，请通过编辑 `HEARTBEAT.md` 使用受保护的 heartbeat 作业，而不是创建聊天自动化。

使用“自动化”视图可以：

- 按全部、活动、已暂停、需要关注或系统作业筛选。
- 按任务名称、消息、触发命令、关联话题、计划或状态搜索。
- 按下次运行、上次运行、更新时间或名称排序。
- 立即运行计划自动化。
- 暂停或恢复、重命名或删除用户创建的自动化。
- 复制本地触发器的 CLI 命令。
- 在不更改的情况下检查受保护的系统自动化。

搜索接受纯文本和字段过滤器，例如 `name:backup`、
`chat:WeChat`、`schedule:09:30`、`cron:"0 23 * * *"`、`trigger` 和
`status:paused`。

未关联话题的自动化无法从 WebUI 启用或运行，因为 nanobot 不知道应将计划回合传递到哪里。请从目标话题或 channel 重新创建它，以便该自动化拥有完整上下文。

本地触发器没有 WebUI 的“立即运行”操作，因为每次运行都需要一条消息。请使用复制的 `nanobot trigger ...` 命令，并将 `"message"` 替换为应传递的内容。

## 设置

“设置”是用于浏览器 session 和由 gateway 支持的运行时配置的控制界面。使用它可以查看或调整 model 预设、provider、图像生成、语音转录、web tool、聊天 channel、Apps、自动化、Skills、运行时身份以及高级安全控制。

某些设置会立即生效。影响 gateway 或 agent 进程的运行时设置可能需要重启；WebUI 会在相关控件旁显示该要求。

仅限浏览器的显示偏好设置（例如文件编辑显示模式）会立即对当前浏览器生效，并且不会更改 gateway 配置。

## LAN 访问

要从同一网络上的另一台设备打开 WebUI，请将 WebSocket channel 绑定到所有接口，并设置 token 或 token 签发密钥：

```json
{
  "channels": {
    "websocket": {
      "host": "0.0.0.0",
      "port": 8765,
      "tokenIssueSecret": "your-secret-here"
    }
  }
}
```

除非配置了 `token` 或 `tokenIssueSecret`，否则 gateway 会拒绝在 `host` 设置为 `"0.0.0.0"` 时启动。gateway 启动后，请从另一台设备打开
`http://<your-ip>:8765`，并在登录表单中输入密钥。

拥有有效 token 的远程 WebUI 客户端可以查看和使用 Apps。默认会阻止安装缺失的 nanobot 支持包的操作，例如添加 channel 依赖项。若要让受信任的远程管理员通过 WebUI 更改 Python 环境，请明确选择启用：

```json
{
  "tools": {
    "webuiAllowRemotePackageInstall": true
  }
}
```

仅在私有部署中使用此功能，并确保每个已认证的 WebUI 用户都受信任，可更改 nanobot 运行所在的 Python 环境。若你通过 Nginx、Caddy、Cloudflare Tunnel 或类似服务发布 WebUI，请将其视为远程访问；除非这是有意为之，否则请保持禁用包安装。

可选功能安装会使用 pip 配置的包索引，包括
`PIP_INDEX_URL`。

当 WebUI 暴露在私有且受信任的网络之外时，请保持禁用远程包安装。

## 故障排除

如果页面无法打开，请按以下顺序检查：

1. `nanobot agent -m "Hello!"` 能在相同的 Python 环境中运行。
2. `~/.nanobot/config.json` 未将 `channels.websocket.enabled` 显式设置为 `false`。
3. `nanobot gateway` 仍在运行。
4. 你打开的是端口 `8765`，而不是 gateway 健康检查端口。
5. LAN 访问使用 `host: "0.0.0.0"` 以及 token 或 token 签发密钥。

有关详细诊断信息，请参阅
[`troubleshooting.md#webui-problems`](troubleshooting-zh.md#webui-problems)。
有关前端开发，请参阅 [`../webui/README.md`](../webui/README.md)。
