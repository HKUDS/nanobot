# 配置

配置文件：`~/.nanobot/config.json`

这是完整参考文档。如果这是你首次安装，请从 [`quick-start.md`](quick-start-zh.md) 开始。如果你正在选择 model 或修复 provider/model 匹配问题，请先使用 [`providers.md`](providers-zh.md)，然后返回此处查看精确字段和高级选项。

对于常规本地使用，编辑 JSON 前优先使用 WebUI：**Settings → Models** 管理 model 选择和 provider 凭据，**Settings → Channels** 引导完成聊天平台设置，其他 Settings 页面涵盖内置功能，**Apps** 管理 CLI App 和 MCP 集成。当你需要高级字段、自动化部署，或有意将配置作为代码管理时，直接编辑 `config.json`。

下方的 JSON 示例通常是要合并到现有配置中的部分片段，而不是完整的替换文件。有关 config、workspace、gateway、channel、session、tool 和 memory 的概念模型，请参阅 [`concepts.md`](concepts-zh.md)。

生成的 `config.json` 使用 camelCase 键，例如 `apiKey` 和 `intervalS`。出于兼容性考虑也接受 snake_case 键，但文档优先使用 camelCase，因为这是 nanobot 写回磁盘时采用的格式。

对于设置和运行时故障，请在同时更改多个配置区域之前，先遵循 [`troubleshooting.md`](troubleshooting-zh.md) 中的诊断顺序。

> [!NOTE]
> 如果你的配置文件早于当前 schema，请运行 `nanobot onboard --refresh`。nanobot 会添加缺失的默认字段，同时保留现有值。

## 配置指南

本页面是完整的配置参考。对于面向任务的设置，请先使用针对性的指南，再返回此处查看精确字段和默认值。

| 任务 | 指南 |
|---|---|
| 添加 MCP tool | [`guides/configure-mcp-tools.md`](guides/configure-mcp-tools-zh.md) |
| 启用网页搜索和网页抓取 | [`guides/configure-web-search.md`](guides/configure-web-search-zh.md) |
| 配置 model 回退 | [`guides/configure-model-fallback.md`](guides/configure-model-fallback-zh.md) |
| 添加 OpenAI 兼容的 provider | [`guides/configure-openai-compatible-provider.md`](guides/configure-openai-compatible-provider-zh.md) |
| 添加 Langfuse 可观测性 | [`guides/configure-langfuse-observability.md`](guides/configure-langfuse-observability-zh.md) |
| 保护本地 AI agent | [`guides/secure-local-ai-agent.md`](guides/secure-local-ai-agent-zh.md) |
| 部署 gateway | [`guides/deploy-nanobot-gateway.md`](guides/deploy-nanobot-gateway-zh.md) |

## 快速跳转

| 需求 | 章节 |
|---|---|
| 将密钥排除在 `config.json` 外 | [用于密钥的环境变量](#environment-variables-for-secrets) |
| 使用环境变量调整进程级行为 | [运行时环境变量](#runtime-environment-variables) |
| 追踪 model 调用 | [Langfuse 可观测性](#langfuse-observability) |
| 配置凭据和端点 | [Providers](#providers) |
| 命名和切换 model 选择 | [Model Preset](#model-presets) |
| 添加回退链 | [Model 回退](#model-fallbacks) |
| 配置语音转录 | [转录设置](#transcription-settings) |
| 调整 channel 默认值 | [Channel 设置](#channel-settings) |
| 配置网页搜索和抓取 | [网页 Tool](#web-tools) |
| 启用图像生成 | [图像生成](#image-generation) |
| 添加 MCP server | [MCP](#mcp-model-context-protocol) |
| 查看 shell、workspace 和 SSRF 控制 | [安全性](#security) |
| 控制访问和配对 | [配对](#pairing) |
| 调整 gateway job、session 和 tool | [Gateway Heartbeat](#gateway-heartbeat)、[自动压缩](#auto-compact)、[统一 Session](#unified-session)、[Tool Hint 最大长度](#tool-hint-max-length) |

## 设置位置

如果 WebUI 未提供你需要的选项，请从下方任务开始。大多数高级更改涉及一个 config 章节和一条验证命令。

| 任务 | 首先检查的键 | 验证方式 | 深入了解 |
|---|---|---|---|
| 让首次 model 回复正常工作 | `providers.<name>.apiKey`、可选的 `providers.<name>.apiBase`、`modelPresets.<preset>`、`agents.defaults.modelPreset` | `nanobot status`，然后运行 `nanobot agent -m "Hello!"` | [Providers](#providers)、[Model Preset](#model-presets) |
| 添加回退 model | `modelPresets.<fallback>`、`agents.defaults.fallbackModels` | `nanobot status`，然后正常运行 agent | [Model 回退](#model-fallbacks) |
| 将密钥排除在 config 文件外 | 任意字符串值中的 `${ENV_VAR}` 占位符 | 从设置该变量的相同环境中启动 nanobot | [用于密钥的环境变量](#environment-variables-for-secrets) |
| 打开随附的 WebUI | `channels.websocket.enabled`、可选的 `channels.websocket.port`、`channels.websocket.tokenIssueSecret` | `nanobot webui` | [Channel 设置](#channel-settings)、[WebSocket 文档](websocket-zh.md) |
| 连接一个聊天 app | `channels.<channel>.enabled`、channel 凭据、可选的配对或 `channels.<channel>.allowFrom` | `nanobot channels status`，然后运行 `nanobot gateway --verbose` | [Channel 设置](#channel-settings)、[聊天 App](chat-apps-zh.md) |
| 启用语音转录 | `transcription.enabled`、`transcription.provider`、对应的 `providers.<name>.apiKey` | 通过已配置的界面发送或上传一条简短语音消息 | [转录设置](#transcription-settings) |
| 启用网页搜索或抓取 | `tools.web.search.*`、`tools.web.fetch.*`、可选的 `tools.ssrfWhitelist` | 提出一个需要当前网页信息的问题，必要时检查日志 | [网页 Tool](#web-tools)、[安全性](#security) |
| 启用图像生成 | `tools.imageGeneration.enabled`、`tools.imageGeneration.provider`、`tools.imageGeneration.model`、对应的 provider 凭据 | 在 WebUI 中启用 Image Generation 并发送一个图像请求 | [图像生成](#image-generation) |
| 通过 MCP 添加外部 tool | `tools.mcpServers.<name>` | 启动 `nanobot gateway --verbose` 并检查启动/tool 日志 | [MCP](#mcp-model-context-protocol) |
| 加强 tool 和网络安全性 | `tools.restrictToWorkspace`、`tools.exec.sandbox`、`tools.ssrfWhitelist`、`channels.*.allowFrom` | 通过你计划公开的 channel 或 CLI 运行相同工作流 | [安全性](#security)、[配对](#pairing) |
| 调整请求超时或进程并发数 | `NANOBOT_LLM_TIMEOUT_S`、`NANOBOT_STREAM_IDLE_TIMEOUT_S`、`NANOBOT_MAX_CONCURRENT_REQUESTS` | 从相同环境中启动 nanobot，并检查启动/运行时日志 | [运行时环境变量](#runtime-environment-variables) |
| 运行多个隔离的 bot | 分别使用 `--config` 和 `--workspace` 路径；进程同时运行时，还需使用不同的 `gateway.port` 或 channel 端口 | 对 `nanobot status`、`agent`、`webui`、`gateway` 和 `serve` 使用相同的显式路径 | [多个实例](multiple-instances-zh.md)、[CLI 参考](cli-reference-zh.md) |
| 观察 model 调用 | `LANGFUSE_SECRET_KEY`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_BASE_URL` 环境变量 | 运行一次 model 调用，然后检查对应的 Langfuse 项目 | [Langfuse 可观测性](#langfuse-observability) |

## 用于密钥的环境变量

你可以使用在启动时从环境变量解析的 `${VAR_NAME}` 引用，而不是将密钥直接存储在 `config.json` 中：

```json
{
  "channels": {
    "telegram": { "token": "${TELEGRAM_TOKEN}" },
    "email": {
      "imapPassword": "${IMAP_PASSWORD}",
      "smtpPassword": "${SMTP_PASSWORD}"
    }
  },
  "providers": {
    "groq": { "apiKey": "${GROQ_API_KEY}" }
  }
}
```

`config.json` 中的任何字符串值都可以使用 `${VAR_NAME}`。解析仅在启动时于 memory 中运行一次，解析后的值绝不会写回磁盘，因此通过 `nanobot onboard` 或 WebUI 编辑 config 时会保留占位符。

如果引用的变量未设置，nanobot 会快速失败，并报告精确的 config 字段和变量名称，而不会回显字段值。使用相同的 `--config` 路径运行 `nanobot status` 以检查问题。

### 更多示例

**MCP server** — 同时适用于 stdio `env` 和 HTTP `headers`：

```json
{
  "tools": {
    "mcpServers": {
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
      },
      "remote": {
        "url": "https://example.com/mcp/",
        "headers": { "Authorization": "Bearer ${REMOTE_MCP_TOKEN}" }
      }
    }
  }
}
```

**网页搜索 provider：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "${BRAVE_API_KEY}"
      }
    }
  }
}
```

### 在启动时加载变量

选择适合你部署方式的方法即可，nanobot 仅在启动时读取 `os.environ`，因此任何能够填充进程环境的机制都可用。

**systemd** — 在 service unit 中使用 `EnvironmentFile=`，从仅部署用户可读的文件加载变量：

```ini
# /etc/systemd/system/nanobot.service (excerpt)
[Service]
EnvironmentFile=/home/youruser/nanobot_secrets.env
User=nanobot
ExecStart=...
```

```bash
# /home/youruser/nanobot_secrets.env (mode 600, owned by youruser)
TELEGRAM_TOKEN=your-token-here
IMAP_PASSWORD=your-password-here
```

**Docker** — 将 env 文件传递给本地构建的 image（每行一个 `KEY=VALUE`），或使用 `-e KEY=value`：

```bash
docker run --rm --env-file=./nanobot.env \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  nanobot agent -m "Hello"
```

**direnv** — 在工作目录中放置 `.envrc` 并运行 `direnv allow`：

```bash
# .envrc (auto-loaded by direnv)
export TELEGRAM_TOKEN=your-token-here
export ANTHROPIC_API_KEY=...
```

**密钥管理器（1Password、Bitwarden、pass）** — 包装进程，使密钥仅在运行期间作为 env var 存在，绝不落盘：

```bash
# 1Password — references in .env.tpl look like `op://Vault/Item/field`
op run --env-file=.env.tpl -- nanobot agent

# pass (passwordstore.org)
ANTHROPIC_API_KEY="$(pass show api/anthropic)" nanobot agent

# Bitwarden
ANTHROPIC_API_KEY="$(bw get password api/anthropic)" nanobot agent
```

## 运行时环境变量

这些变量是进程级开关。请在启动 nanobot 的同一终端、service unit、container 或 supervisor 中设置它们。

### 运行时控制

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `NANOBOT_MAX_CONCURRENT_REQUESTS` | `3` | 同时运行的入站 agent 请求的最大数量。必须为整数；设置为 `0` 或负值表示不限制。 |
| `NANOBOT_LLM_TIMEOUT_S` | `300` | 以秒为单位的实际时间超时。普通请求使用此值；streaming 请求使用 300 秒或此值两倍中的较大值。设置为 `0` 可禁用。持续目标轮次会绕过此实际时间上限。 |
| `NANOBOT_STREAM_IDLE_TIMEOUT_S` | `90` | streaming provider 使用的 streaming 空闲超时，单位为秒。无效或非正值会被忽略；超过 `3600` 的值会被限制。 |
| `NANOBOT_OPENAI_COMPAT_TIMEOUT_S` | `120` | OpenAI 兼容 provider 的 HTTP 请求超时，单位为秒。无效或非正值会被忽略。 |
| `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` | 未设置 | 标记外部 workspace sandbox 已强制实施。真值（`1`、`true`、`yes`、`on`、`enabled`）使用 `NANOBOT_WORKSPACE_SANDBOX_PROVIDER` 作为标签；任何其他非假值都会被视为 provider 名称。 |
| `NANOBOT_WORKSPACE_SANDBOX_PROVIDER` | `unknown` | 当 `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` 为真值时，外部 workspace sandbox 的显示标签，例如 `macos_app_sandbox` 或 `bwrap`。 |
| `NANOBOT_SANDBOX_ENFORCED` | 未设置 | `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` 的旧版兼容别名。 |
| `NANOBOT_TMUX_SOCKET_DIR` | `${TMPDIR:-/tmp}/nanobot-tmux-sockets` | 随附 `tmux` skill script 使用的 socket 目录。 |
### 安装程序、构建和 WebUI 开发

| 变量 | 默认值 | 描述 |
|----------|---------|-------------|
| `NANOBOT_BIN_DIR` | `$HOME/.local/bin` | macOS/Linux 上的安装程序启动器目录。 |
| `NANOBOT_VENV` | `$HOME/.nanobot/venv` | 安装程序回退机制使用的托管虚拟环境路径。 |
| `NANOBOT_SKIP_WIZARD` | 未设置 | 设置为 `1`，以跳过单命令安装后的自动 WebUI 或向导设置。 |
| `NANOBOT_SKIP_WEBUI_BUILD` | 未设置 | 设置为 `1`，以跳过软件包构建期间的 WebUI 打包。 |
| `NANOBOT_FORCE_WEBUI_BUILD` | 未设置 | 设置为 `1`，即使 `nanobot/web/dist/index.html` 已存在，也会重新构建打包的 WebUI。 |
| `NANOBOT_EXTRAS` | 未设置 | 包含以逗号分隔的 Python extras（例如 `bedrock`）的 Docker 构建参数。 |
| `NANOBOT_CHANNELS` | `whatsapp` | 包含以逗号分隔的 channel 的 Docker 构建参数，这些 channel 的清单依赖项会被预先安装。 |
| `NANOBOT_API_URL` | `http://127.0.0.1:8765` | Vite WebUI 开发服务器代理的 gateway 目标。 |

`NANOBOT_RESTART_*` 和 `NANOBOT_PATH_*` 等内部变量由 nanobot 自身设置，不属于受支持的用户配置范围。

## Langfuse 可观测性

nanobot 可以通过 Langfuse 的 OpenAI SDK 包装器跟踪与 OpenAI 兼容的 provider 调用。此功能通过环境变量配置，而不是通过 `config.json` 配置。

在运行 nanobot 的同一 Python 环境中安装可选软件包：

```bash
nanobot plugins enable langfuse
```

启动 `nanobot agent`、`nanobot gateway` 或 `nanobot serve` 之前，设置 Langfuse 凭据：

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
```

对于 PowerShell：

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
```

当设置了 `LANGFUSE_SECRET_KEY` 且已安装 `langfuse` 软件包时，nanobot 会为 OpenAI 兼容的 provider 使用 `langfuse.openai.AsyncOpenAI`，使 model 请求在后台发送到 Langfuse。如果设置了 secret key 但缺少 `langfuse`，nanobot 会记录警告，并回退到常规 OpenAI 客户端。

使用与项目匹配的 Langfuse 区域或自托管 URL。[Langfuse OpenAI SDK 文档](https://langfuse.com/integrations/model-providers/openai-py) 使用 `LANGFUSE_BASE_URL` 配置云区域和自托管实例。

跟踪涵盖通过 nanobot 的 OpenAI 兼容客户端路径调用的 provider。不使用该客户端的原生 provider 可能不会生成 Langfuse OpenAI 包装器跟踪记录。
## 提供商

> [!TIP]
> - **语音转写**：语音消息和 WebUI 麦克风输入使用共享的顶层 `transcription` 设置。默认的 `transcription.provider` 值为 `"groq"`；对于 OpenAI Whisper，将其设置为 `"openai"`；对于 OpenRouter 语音转文本模型，设置为 `"openrouter"`；对于 Xiaomi MiMo ASR，设置为 `"xiaomi_mimo"`；对于 AssemblyAI，设置为 `"assemblyai"`。API 密钥仍存储在对应的 `providers.<provider>` 配置中。
> - **MiniMax Coding Plan**：面向 nanobot 社区的专属折扣链接：[海外](https://platform.minimax.io/subscribe/coding-plan?code=9txpdXw04g&source=link) · [中国大陆](https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link)
> - **MiniMax（中国大陆）**：如果你的 API 密钥来自 MiniMax 的中国大陆平台（minimaxi.com），请在 minimax provider 配置中设置 `"apiBase": "https://api.minimaxi.com/v1"`。
> - **MiniMax 思考模式**：`providers.minimaxAnthropic` 是配置 `reasoningEffort` / 思考模式的配置块。MiniMax 通过其兼容 Anthropic 的端点提供该能力，因此 nanobot 将其作为独立 provider，而不是在通用的兼容 OpenAI 的 `minimax` 端点上猜测 MiniMax 特有的思考参数。它使用相同的 `MINIMAX_API_KEY`。默认的兼容 Anthropic 的基础 URL：`https://api.minimax.io/anthropic`；中国大陆使用 `https://api.minimaxi.com/anthropic`。
> - **Kimi Coding Plan**：使用 `providers.kimiCoding`，并将 `provider` 设置为 `"kimi_coding"`，以使用 Kimi 专用的 Anthropic Messages API 端点。该端点要求兼容 Claude 的 `User-Agent`；nanobot 默认发送 `claude-code/0.1.0`，如果你的账户要求不同的值，可以通过 `extraHeaders.User-Agent` 覆盖。
> - **VolcEngine / BytePlus Coding Plan**：订阅端点通过专用 provider `volcengineCodingPlan` 或 `byteplusCodingPlan` 配置，与按量付费的 `volcengine` / `byteplus` provider 分开。
> - **OpenCode Zen / Go**：`providers.opencode`（规范 Zen）、兼容旧版的 `providers.opencodeZen` 以及 `providers.opencodeGo` 使用相同的 `OPENCODE_API_KEY`，但会路由到不同的 OpenCode gateway。这些 provider 使用 OpenCode 兼容 OpenAI 的 `chat/completions` 端点；请从该端点系列中选择 model ID。
> - **Zhipu Coding Plan**：如果你使用 Zhipu 的 coding plan，请在 zhipu provider 配置中设置 `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"`。
> - **Alibaba Cloud BaiLian**：如果你使用 Alibaba Cloud BaiLian 兼容 OpenAI 的端点，请在 dashscope provider 配置中设置 `"apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"`。
> - **ModelScope**：如果你使用 ModelScope 兼容 OpenAI 的端点，请在 modelscope provider 配置中设置 `"apiBase": "https://api-inference.modelscope.cn/v1"`。
> - **StepFun Step Plan**：如果你订阅了 StepFun 的 Step Plan，请在 stepfun provider 配置中设置 `"apiBase": "https://api.stepfun.ai/step_plan/v1"`。支持的 model 包括 `step-3.5-flash`、`step-3.5-flash-2603` 和 `step-router-v1`。
> - **Step Fun（中国大陆）**：如果你的 API 密钥来自 Step Fun 的中国大陆平台（stepfun.com），请在 stepfun provider 配置中设置 `"apiBase": "https://api.stepfun.com/v1"`。
> - **Xiaomi MiMo 思考模式**：MiMo model（例如 `mimo-v2.5-pro`）默认启用思考。使用 `agents.defaults.reasoningEffort: "none"` 可将其禁用，或使用 `"low"` / `"medium"` / `"high"` 保持启用。省略该字段会保留 provider 针对每个 model 的默认设置。
> - **Xiaomi MiMo Token Plan**：如果你使用 MiMo 的 token plan，请在 xiaomi_mimo provider 配置中设置 `"apiBase": "https://token-plan-sgp.xiaomimimo.com/v1"`。
> - **自定义兼容 OpenAI 的 provider**：除了内置的 `custom` provider 外，`providers` 下的任何额外键都可以定义自己的兼容 OpenAI 端点。例如，`providers.companyProxy.apiBase` 加上 `modelPresets.primary.provider: "companyProxy"` 会创建一个独立的自定义 provider。设置 `apiBase`；仅当端点要求时才设置 `apiKey`。此命名自定义路径仅使用兼容 OpenAI 的请求格式。对于兼容 Anthropic 的代理，请使用 `providers.anthropic.apiBase`，并将 `provider` 设置为 `"anthropic"`。
> - **Provider 级代理**：`providers.<name>.proxy` 仅将相应 provider 的请求通过 HTTP 代理路由。兼容 OpenAI 的 provider、`openai_codex` 和 `xai_grok` 支持此设置。`anthropic`、`bedrock`、`azure_openai` 和 `github_copilot` 等原生 provider 后端会拒绝 `proxy`。

| Provider | 用途 | 获取 API 密钥 |
|----------|---------|-------------|
| `custom` | 任意兼容 OpenAI 的端点 | — |
| `openrouter` | 托管 model 系列的 LLM gateway + 语音转写（STT model） | [openrouter.ai](https://openrouter.ai) |
| `edenai` | Eden AI 兼容 OpenAI 的 model 目录的 LLM gateway | [app.edenai.run](https://app.edenai.run/) |
| `opencode` | LLM gateway（OpenCode Zen coding-agent model） | [opencode.ai/docs/zen](https://opencode.ai/docs/zen/) |
| `opencode_zen` | LLM gateway（OpenCode Zen 的旧版别名） | [opencode.ai/docs/zen](https://opencode.ai/docs/zen/) |
| `opencode_go` | LLM gateway（OpenCode Go 低成本 coding model） | [opencode.ai/docs/go](https://opencode.ai/docs/go/) |
| `huggingface` | LLM（Hugging Face Inference Providers） | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `skywork` | LLM（Skywork / APIFree API gateway） | [apifree.ai](https://www.apifree.ai) |
| `volcengine` | LLM（VolcEngine，按量付费） | [Coding Plan](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [volcengine.com](https://www.volcengine.com) |
| `volcengine_coding_plan` | LLM（VolcEngine Coding Plan 订阅端点） | [volcengine.com](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) |
| `byteplus` | LLM（VolcEngine 国际版，按量付费） | [Coding Plan](https://www.byteplus.com/en/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [byteplus.com](https://www.byteplus.com) |
| `byteplus_coding_plan` | LLM（BytePlus Coding Plan 订阅端点） | [byteplus.com](https://www.byteplus.com/en/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) |
| `anthropic` | LLM（Claude 直连） | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM（Azure OpenAI） | [portal.azure.com](https://portal.azure.com) |
| `bedrock` | LLM（AWS Bedrock Converse、Claude/Nova/Llama 等） | [aws.amazon.com/bedrock](https://aws.amazon.com/bedrock/) |
| `openai` | LLM + 语音转写（Whisper） | [platform.openai.com](https://platform.openai.com) |
| `assemblyai` | 仅语音转写 | [assemblyai.com](https://www.assemblyai.com/) |
| `deepseek` | LLM（DeepSeek 直连） | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + 语音转写（Whisper，默认） | [console.groq.com](https://console.groq.com) |
| `minimax` | LLM（MiniMax 直连） | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `minimax_anthropic` | LLM（MiniMax 兼容 Anthropic 的端点，思考模式） | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `gemini` | LLM（Gemini 直连） | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM（API gateway，可访问所有 model） | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM（SiliconFlow/硅基流动） | [siliconflow.cn](https://siliconflow.cn) |
| `novita` | LLM（Novita AI 兼容 OpenAI 的 gateway） | [novita.ai](https://novita.ai) |
| `dashscope` | LLM（Qwen） | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `modelscope` | LLM（ModelScope/魔搭社区）+ 图像生成 | [modelscope.cn](https://modelscope.cn) |
| `moonshot` | LLM（Moonshot/Kimi） | [platform.kimi.com](https://platform.kimi.com?aff=nanobot) |
| `kimi_coding` | LLM（Kimi Coding Plan，Anthropic Messages API） | [platform.kimi.com](https://platform.kimi.com?aff=nanobot) |
| `zhipu` | LLM（Zhipu GLM） | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `xiaomi_mimo` | LLM（MiMo） | [platform.xiaomimimo.com](https://platform.xiaomimimo.com) |
| `longcat` | LLM（LongCat） | [longcat.chat](https://longcat.chat/platform/docs/zh/) |
| `ant_ling` | LLM（Ant Ling / 蚂蚁百灵） | [developer.ant-ling.com](https://developer.ant-ling.com/en/docs/api-reference/openai/) |
| `ollama` | LLM（本地，Ollama） | — |
| `lm_studio` | LLM（本地，LM Studio） | — |
| `atomic_chat` | LLM（本地，[Atomic Chat](https://atomic.chat/)） | — |
| `mistral` | LLM | [docs.mistral.ai](https://docs.mistral.ai/) |
| `stepfun` | LLM（Step Fun/阶跃星辰）+ 语音转写（ASR） | [platform.stepfun.com](https://platform.stepfun.com) |
| `ovms` | LLM（本地，OpenVINO Model Server） | [docs.openvino.ai](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) |
| `vllm` | LLM（本地，任意兼容 OpenAI 的服务器） | — |
| `nvidia` | LLM（NVIDIA NIM） | [build.nvidia.com](https://build.nvidia.com/) |
| `openai_codex` | LLM（Codex，OAuth） | `nanobot provider login openai-codex --set-main` |
| `xai_grok` | LLM（Grok，OAuth） | `nanobot provider login xai-grok --set-main` |
| `github_copilot` | LLM（GitHub Copilot，OAuth） | `nanobot provider login github-copilot` |
| `qianfan` | LLM（Baidu Qianfan） | [cloud.baidu.com](https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26) |

<details>
<summary><b>OpenAI</b></summary>

默认情况下，OpenAI 使用 `apiType: "auto"`：nanobot 通常调用 Chat Completions，并在适用时将 GPT-5/o-series 或显式指定 `reasoningEffort` 的请求路由到 Responses API。你可以强制使用特定的 API 界面：

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}",
      "apiType": "chat_completions"
    }
  }
}
```

有效的 `apiType` 值必须是 `auto`、`chat_completions` 和 `responses`。

`extraBody` 遵循所选 OpenAI API 界面的格式。使用 Chat Completions 时，nanobot 会将其作为 SDK 的 `extra_body` 值直接传递。使用 Responses 时，请按照 Responses API 请求体格式进行配置；nanobot 会将普通的顶层字段合并到 Responses 请求体中，将 `extraBody.tools` 追加到生成的 function tools 之后，并在不产生重复项的情况下合并 `extraBody.include`：

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}",
      "apiType": "responses",
      "extraBody": {
        "tools": [{ "type": "web_search" }],
        "include": ["web_search_call.action.sources"]
      }
    }
  }
}
```

WebUI 的 OpenAI web-search 开关会写入相应的 `apiType` 和 `extraBody.tools`
字段。托管的 search tool 会在该请求中替换 nanobot 同名的本地 `web_search` function，而
`web_fetch` 等其他 tool 仍然可用。

</details>

<details>
<summary><b>DeepSeek 原生 web search</b></summary>

DeepSeek V4 Flash 使用 DeepSeek 原生的 Responses API。由于不需要单独付费的附加服务，其 provider 托管的 web search 默认启用。可以从 WebUI provider 设置中将其关闭，也可以通过以下配置关闭：

```json
{
  "providers": {
    "deepseek": {
      "apiKey": "${DEEPSEEK_API_KEY}",
      "extraBody": {
        "tools": []
      }
    }
  }
}
```

该开关适用于 `deepseek-v4-flash`；仍使用 Chat Completions 的 DeepSeek model 无法使用此 Responses tool。原生 search 调用会显示在 WebUI activity stream 中，其不透明的输出项会被保留，以便在多轮 Responses 状态重放时使用。

</details>

<a id="responses-state-and-compaction"></a>
### Responses 对话状态与压缩

使用 Responses API 的 provider 可以在对话中保留推理上下文，这有助于处理多步骤任务。受支持的 provider 还可以自动压缩较长的对话。

nanobot 会自动保留 OpenAI Responses、OpenAI Codex、Azure OpenAI、DeepSeek V4 Flash 以及兼容的 GitHub Copilot model 的 Responses 对话状态。当 provider 支持原生压缩时，也会自动进行压缩。阈值根据活动 model 的上下文窗口和预留输出空间计算；无需进行 provider 配置。

<details>
<summary><b>Azure OpenAI</b></summary>

`azure_openai` provider 通过 OpenAI **Responses API**（`/openai/v1/responses`）访问 Azure OpenAI 资源。model 名称映射到 **deployment 名称**，而不是 OpenAI model ID。支持两种身份验证模式。

**模式 1：静态 API 密钥**（最简单）

```json
{
  "providers": {
    "azure_openai": {
      "apiKey": "${AZURE_OPENAI_API_KEY}",
      "apiBase": "https://my-resource.openai.azure.com"
    }
  },
  "modelPresets": {
    "azure": {
      "provider": "azure_openai",
      "model": "my-gpt-5-deployment"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "azure"
    }
  }
}
```

**模式 2：通过 `DefaultAzureCredential` 使用 Microsoft Entra ID（Azure AD）**

省略 `apiKey`（或将其留空 / 未设置）。provider 会回退到 [`DefaultAzureCredential`](https://learn.microsoft.com/azure/developer/python/sdk/authentication/credential-chains#defaultazurecredential-overview)，并为每个请求获取作用域为 `https://cognitiveservices.azure.com/.default` 的 bearer token。Azure SDK 自带的基于 MSAL 的缓存会返回有效 token，无需网络往返。

```json
{
  "providers": {
    "azure_openai": {
      "apiBase": "https://my-resource.openai.azure.com"
    }
  },
  "modelPresets": {
    "azure": {
      "provider": "azure_openai",
      "model": "my-gpt-5-deployment"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "azure"
    }
  }
}
```

安装可选依赖：

```bash
nanobot plugins enable azure
```

`DefaultAzureCredential` 按顺序遍历以下链，并使用第一个成功的身份：

1. **EnvironmentCredential** — 读取 `AZURE_TENANT_ID`、`AZURE_CLIENT_ID`，以及以下变量之一：`AZURE_CLIENT_SECRET` / `AZURE_CLIENT_CERTIFICATE_PATH` / `AZURE_USERNAME` + `AZURE_PASSWORD`。
2. **WorkloadIdentityCredential** — 用于 AKS workload identity / 联合 token（`AZURE_FEDERATED_TOKEN_FILE`）。
3. **ManagedIdentityCredential** — 用于 Azure VM、App Service、Functions、Container Apps 等。
4. **AzureCliCredential** — 使用开发机上 `az login` 获取的 token。
5. **AzurePowerShellCredential** — 使用 `Connect-AzAccount` 获取的 token。
6. **AzureDeveloperCliCredential** — 使用 `azd auth login` 获取的 token。
7. **InteractiveBrowserCredential** *(默认禁用)*。

最终为请求签名的身份**必须在 Azure OpenAI 资源上被分配 `Cognitive Services OpenAI User` RBAC 角色**（或更高权限）。如果没有该角色，首次请求时会看到 `401`/`403` 错误。

> 两种模式下都必须设置 `apiBase`——它是 Azure 资源端点，无法推断。如果既未设置 `apiKey`，又未安装 `azure-identity`，provider 会抛出明确错误，并指向 `nanobot plugins enable azure`。

</details>

<details>
<summary><b>Skywork / APIFree</b></summary>

Skywork 使用 APIFree 的 OpenAI 兼容 Agent API 端点。配置一次 provider 后，即可使用 `skywork-ai/skyclaw-v1` 等 Skywork model ID。

```json
{
  "providers": {
    "skywork": {
      "apiKey": "${SKYWORK_API_KEY}",
      "apiBase": "https://api.apifree.ai/agent/v1"
    }
  },
  "modelPresets": {
    "skywork": {
      "provider": "skywork",
      "model": "skywork-ai/skyclaw-v1",
      "maxTokens": 32768,
      "contextWindowTokens": 131072
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "skywork"
    }
  }
}
```

如果环境使用该名称保存凭据，也可以在 `apiKey` 中引用 `${APIFREE_API_KEY}`。

</details>

<details>
<summary><b>AWS Bedrock（Converse API）</b></summary>

Bedrock 使用原生的 `bedrock-runtime` Converse API，因此可以调用 Claude Opus 4.7、Claude Sonnet、Amazon Nova、Meta Llama、Mistral、Qwen 以及其他支持 Converse 的 model ID。它支持普通聊天、流式传输、tool 调用、tool 结果、token 使用量和 Bedrock 错误元数据。

此 provider 用于 Bedrock 的原生 Converse API，而不是 Bedrock 的 OpenAI 兼容 `/openai/v1` 端点。对于 OpenAI 兼容的 Bedrock model，仍可以使用 `custom`，前提是确实需要该 API 接口。

先安装 Bedrock 支持：

```bash
nanobot plugins enable bedrock
```

> [!NOTE]
> 如果在 `boto3` 成为可选依赖之前配置过 Bedrock，请在升级后运行
> `nanobot plugins enable bedrock`。否则 provider 首次尝试创建 Bedrock client 时会失败。

**1. 配置凭据**

使用标准 AWS 凭据链（`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`、AWS profile 或 IAM role）。IAM 身份需要以下权限：

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": "*"
}
```

也可以将 `providers.bedrock.apiKey` 设置为 Bedrock API key；nanobot 会将其导出为 `AWS_BEARER_TOKEN_BEDROCK`，供 AWS SDK 使用。

凭据选项：

- **AWS CLI/default profile**：将 `apiKey` 和 `profile` 留空，然后运行 `aws configure`，或提供 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`。
- **命名 AWS profile**：将 `profile` 设置为 `~/.aws/config` 或 `~/.aws/credentials` 中的 profile。
- **IAM role**：在 EC2/ECS/Lambda 上，将 `apiKey` 和 `profile` 留空，并附加具有 Bedrock 权限的 role。
- **Bedrock API key**：设置 `apiKey` 或 `AWS_BEARER_TOKEN_BEDROCK`；`profile` 可以保持为 `null`。

**2. 最小配置**

对于 Amazon Nova 这类非 Anthropic model：

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1"
    }
  },
  "modelPresets": {
    "bedrockNova": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0",
      "reasoningEffort": null
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "bedrockNova"
    }
  }
}
```

使用 Bedrock API key：

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "apiKey": "${AWS_BEARER_TOKEN_BEDROCK}"
    }
  },
  "modelPresets": {
    "bedrockNova": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0",
      "reasoningEffort": null
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "bedrockNova"
    }
  }
}
```

使用命名 AWS profile：

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "profile": "my-bedrock-profile"
    }
  },
  "modelPresets": {
    "bedrockNova": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "bedrockNova"
    }
  }
}
```

**3. Claude Opus 4.7 示例**

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1"
    }
  },
  "modelPresets": {
    "bedrockClaude": {
      "provider": "bedrock",
      "model": "bedrock/global.anthropic.claude-opus-4-7",
      "reasoningEffort": "medium",
      "maxTokens": 8192
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "bedrockClaude"
    }
  }
}
```

要使用区域路由，请使用 Bedrock 的 inference ID，例如 `bedrock/us.anthropic.claude-opus-4-7`、`bedrock/eu.anthropic.claude-opus-4-7` 或 `bedrock/jp.anthropic.claude-opus-4-7`。

Claude Opus 4.7 不接受 `temperature`、`top_p` 或 `top_k`；nanobot 会针对该 model 自动省略 `temperature`。如果将 `reasoningEffort` 设置为 `low`、`medium`、`high`、`max` 或 `adaptive`，nanobot 会发送 Bedrock 的自适应思考参数。

Bedrock 上的 Anthropic model 还可能要求注册 Anthropic 使用场景，并受 Anthropic 支持的国家/地区限制。如果 Claude 因不支持的国家或地区而失败，并出现有关此问题的 `ValidationException`，请尝试 Amazon Nova 等非 Anthropic Bedrock model，以验证 provider 配置。

**4. Model ID**

在 nanobot 配置中使用带有 `bedrock/` 前缀的 Bedrock model ID 或 inference profile ID。nanobot 在调用 AWS 前会移除该前缀。

示例：

- `bedrock/amazon.nova-micro-v1:0`
- `bedrock/amazon.nova-lite-v1:0`
- `bedrock/global.anthropic.claude-opus-4-7`
- `bedrock/us.anthropic.claude-opus-4-7`
- `bedrock/openai.gpt-oss-20b-1:0`
- `bedrock/meta.llama...`
- `bedrock/mistral...`

请查看 Bedrock 控制台以确认确切的 model ID 和区域可用性。某些 model 要求使用 `us.*`、`eu.*` 或 `global.*` 等跨区域 inference profile ID。

**5. 高级 model 字段**

可以通过 `extraBody` 提供特定于 model 的字段；nanobot 会将其合并到 Converse 的 `additionalModelRequestFields` 中：

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "extraBody": {
        "thinking": {
          "type": "adaptive",
          "effort": "medium",
          "display": "summarized"
        }
      }
    }
  }
}
```

仅在需要自定义 Bedrock Runtime 端点 URL（例如 VPC 端点或 proxy）时使用 `apiBase`。对于普通 AWS 区域，不需要设置它。

当前范围：nanobot 会传递 `messages`、`system`、`inferenceConfig`、`toolConfig` 和 `additionalModelRequestFields`。Bedrock Prompt Management、Guardrails、`serviceTier` 以及其他顶层 Converse 选项目前还不是一等配置字段。

**6. 快速检查**

```bash
# For AWS credential-chain usage:
aws sts get-caller-identity
# API 密钥使用：
export AWS_BEARER_TOKEN_BEDROCK="your-bedrock-api-key"
export AWS_REGION="us-east-1"
```

然后运行：

```bash
nanobot agent -m "Reply with one short sentence."
```

</details>


<details>
<summary><b>OpenAI Codex（OAuth）</b></summary>

Codex 使用 OAuth 而不是 API 密钥，并且需要 ChatGPT Plus 或 Pro 账户。完成身份验证，并通过一条命令将当前旗舰 model 设为活动 agent model：

```bash
nanobot provider login openai-codex --set-main
```

然后运行：

```bash
nanobot agent -m "Hello!"
```

可以从 WebUI provider 设置中启用 Codex Fast 模式，也可以使用以下配置：

```json
{
  "providers": {
    "openaiCodex": {
      "extraBody": {
        "service_tier": "priority"
      }
    }
  }
}
```

此开关会向 Responses API 发送 `service_tier: "priority"` 值。它仅适用于支持 Fast 模式的 model
和账户；关闭此开关即可恢复标准处理模式。
Fast 模式会以更高的速率消耗 Codex credits。有关当前详情，请参阅
[OpenAI Codex 费率卡](https://help.openai.com/en/articles/20001106)。

有关 proxy、远程/无头登录、model 名称或配置键错误，请参阅
[`troubleshooting.md`](troubleshooting-zh.md#provider-and-model-problems)。

</details>


<details>
<summary><b>xAI Grok（OAuth）</b></summary>

使用符合条件的 X Premium / Grok 订阅，无需将 API 密钥写入
`config.json`：

```bash
nanobot provider login xai-grok --set-main
nanobot agent -m "Hello from Grok."
```

默认 model 是 `xai-grok/grok-4.5`，上下文窗口为 500,000 个 token。
该 provider 会读取 xAI 的 model catalog，并且仅当所选 model 声明支持
`supportsBackendSearch` 时，才包含由服务器托管的 `x_search`
tool。不具备此能力的 model 会继续正常运行，但不会使用托管式 X Search。启用后，
搜索会在 xAI 的 Responses API 内部运行，引用会以内联链接的形式返回。
默认启用托管式 X Search，以保留此行为。可以在
WebUI provider 设置中关闭，也可以使用 `providers.xaiGrok.extraBody.tools: []` 关闭。

这是 xAI 订阅 OAuth，而不是 X Developer OAuth。nanobot 遵循
[Grok Build](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md)
使用的公开 OAuth 客户端和 proxy 契约。
浏览器流程使用随机 loopback 回调和 PKCE。生成的 token
会存储在活动实例的 `auth/xai.json` 中（通常为
`~/.nanobot/auth/xai.json`），与 Grok Build 分开存储，因此轮换 refresh
token 不会使彼此失效。

要使用 provider 专用 proxy，请在登录前将以下内容合并到 `config.json`：

```json
{
  "providers": {
    "xaiGrok": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

该 proxy 适用于 OAuth 发现、token 交换/刷新、model catalog
查询以及订阅 model 请求。由于此集成依赖 xAI 的公开 Grok Build 客户端契约，
上游契约发生变化时可能需要更新 nanobot。

</details>


<details>
<summary><b>GitHub Copilot（OAuth）</b></summary>

GitHub Copilot 使用 OAuth 而不是 API 密钥。需要配置一个
[具有套餐的 GitHub 账户](https://github.com/features/copilot/plans)。`config.json` 中不需要
`providers.github_copilot` 块；`nanobot provider login` 会将 OAuth session 存储在 config 外部。

对于 GitHub Enterprise / Copilot for Business，请在登录前设置所需的 endpoint 覆盖：
```bash
export NANOBOT_GITHUB_COPILOT_CLIENT_ID="your-enterprise-client-id"
export NANOBOT_GITHUB_DEVICE_CODE_URL="https://ghe.example/login/device/code"
export NANOBOT_GITHUB_ACCESS_TOKEN_URL="https://ghe.example/login/oauth/access_token"
export NANOBOT_GITHUB_USER_URL="https://api.ghe.example/user"
export NANOBOT_COPILOT_TOKEN_URL="https://api.ghe.example/copilot_internal/v2/token"
export NANOBOT_COPILOT_BASE_URL="https://copilot-api.ghe.example"
```

**1. 登录：**
```bash
nanobot provider login github-copilot
```

**2. 设置 model**（合并到 `~/.nanobot/config.json`）：
```json
{
  "modelPresets": {
    "copilot": {
      "provider": "github_copilot",
      "model": "github-copilot/gpt-4.1"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "copilot"
    }
  }
}
```

**3. 聊天：**
```bash
nanobot agent -m "Hello!"

# Target a specific workspace/config locally
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test -m "Hello!"
```

> Docker 用户：使用 `docker run -it` 进行交互式 OAuth 登录。

</details>

<details>
<summary><b>OpenCode Zen / Go</b></summary>

OpenCode Zen 和 OpenCode Go 可通过 nanobot 内置的
OpenAI-compatible provider 流程使用。它们共享 `OPENCODE_API_KEY` 环境
变量，但使用不同的 provider key 和默认 base URL：

| Provider | 默认 API base | nanobot 接受的 model 前缀 |
|----------|------------------|-----------------------------------|
| `opencode` | `https://opencode.ai/zen/v1` | `opencode/<model-id>` |
| `opencode_zen` | `https://opencode.ai/zen/v1` | `opencode/<model-id>` |
| `opencode_go` | `https://opencode.ai/zen/go/v1` | `opencode-go/<model-id>` |

OpenCode Zen：

```json
{
  "providers": {
    "opencode": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "opencodeZen": {
      "provider": "opencode",
      "model": "opencode/deepseek-v4-pro"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "opencodeZen"
    }
  }
}
```

`providers.opencodeZen` / `provider: "opencode_zen"` 仍可作为现有 config 的兼容别名使用。

OpenCode Go：

```json
{
  "providers": {
    "opencodeGo": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "opencodeGo": {
      "provider": "opencode_go",
      "model": "opencode-go/deepseek-v4-flash"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "opencodeGo"
    }
  }
}
```

OpenCode 自身的文档会在 `responses`、`messages`、
provider-specific model endpoint 以及 `chat/completions` 中列出 model。nanobot 的 OpenCode
provider 使用 OpenAI-compatible 的 `chat/completions` 路径，因此请从该 endpoint 系列中选择 model ID。
`opencode/...` 和 `opencode-go/...` 前缀可用于提高 config 可读性，并会在发送请求前被移除。

</details>

<details>
<summary><b>LongCat（OpenAI-compatible）</b></summary>

LongCat 可通过 nanobot 内置的 OpenAI-compatible provider 流程使用。默认 API base 已指向 `https://api.longcat.chat/openai/v1`，因此通常只需设置 `apiKey`。

```json
{
  "providers": {
    "longcat": {
      "apiKey": "${LONGCAT_API_KEY}"
    }
  },
  "modelPresets": {
    "longcat": {
      "provider": "longcat",
      "model": "LongCat-2.0-Preview",
      "maxTokens": 8192,
      "contextWindowTokens": 1048576
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "longcat"
    }
  }
}
```

当前 LongCat API 文档将 `LongCat-2.0-Preview` 列为受支持的 model。较旧的 `LongCat-Flash-*` model 已于 2026-05-29 被 LongCat 退役。

</details>

<details>
<summary><b>Xiaomi MiMo</b></summary>

当 model 名称包含 `mimo` 时，Xiaomi MiMo model 会由 `xiaomi_mimo` provider 自动检测。默认 API base 为 `https://api.xiaomimimo.com/v1`。

> **Token Plan**：如果使用 MiMo 的 token plan，请将 `apiBase` 覆盖为专用 endpoint：
>
> ```json
> {
>   "providers": {
>     "xiaomi_mimo": {
>       "apiKey": "${XIAOMIMIMO_API_KEY}",
>       "apiBase": "https://token-plan-sgp.xiaomimimo.com/v1"
>     }
>   },
>   "modelPresets": {
>     "mimo": {
>       "provider": "xiaomi_mimo",
>       "model": "xiaomi/mimo-v2.5-pro"
>     }
>   },
>   "agents": {
>     "defaults": {
>       "modelPreset": "mimo"
>     }
>   }
> }
> ```
>
> 使用 MiMo token plan 控制台中的 model ID 和 API 密钥，并在 MiMo 平台上查看最新的受支持 model 名称。

</details>

<details>
<summary><b>StepFun Step Plan（订阅）</b></summary>

Step Plan 是 StepFun 面向高频 AI 开发者提供的基于订阅的服务。如果使用 Step Plan 订阅，请在现有的 `stepfun` provider 配置中覆盖 `apiBase`，使其指向专用的 Step Plan endpoint。

```json
{
  "providers": {
    "stepfun": {
      "apiKey": "${STEPFUN_API_KEY}",
      "apiBase": "https://api.stepfun.ai/step_plan/v1"
    }
  },
  "modelPresets": {
    "stepfun": {
      "provider": "stepfun",
      "model": "step-3.5-flash"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "stepfun"
    }
  }
}
```

受支持的 model 包括 `step-3.5-flash`、`step-3.5-flash-2603` 和 `step-router-v1`。

</details>

<details>
<summary><b>Ant Ling（OpenAI-compatible）</b></summary>

Ant Ling 可通过 nanobot 内置的 OpenAI-compatible provider 流程使用。默认 API base 指向 `https://api.ant-ling.com/v1`，因此通常只需设置 `apiKey`。

```json
{
  "providers": {
    "antLing": {
      "apiKey": "${ANT_LING_API_KEY}"
    }
  },
  "modelPresets": {
    "antLing": {
      "provider": "ant_ling",
      "model": "Ling-2.6-flash"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "antLing"
    }
  }
}
```

官方 OpenAI-compatible model 名称包括 `Ling-2.6-1T`、`Ling-2.6-flash`、`Ling-2.5-1T`、`Ling-1T`、`Ring-2.5-1T` 和 `Ring-1T`。

</details>

<details>
<summary><b>自定义 Provider（任意 OpenAI-compatible API）</b></summary>

直接连接到任意 OpenAI-compatible endpoint，例如 llama.cpp、Together AI、Fireworks、Azure OpenAI 或任何自托管服务器。model 名称会按原样传递。

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "modelPresets": {
    "custom": {
      "provider": "custom",
      "model": "your-model-name"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "custom"
    }
  }
}
```

> 对于不需要身份验证的本地服务器，将 `apiKey` 设置为 `null`。
>
> 对于提供 OpenAI-compatible **chat completions** API 的 provider，应选择 `custom`。它不会强制第三方 endpoint 使用 OpenAI/Azure **Responses API**。
>
> 如果你的 proxy 或 gateway 专门兼容 Responses API，请配置 `azure_openai` provider 结构，并将 `apiBase` 指向该 endpoint：
>
> ```json
> {
>   "providers": {
>     "azure_openai": {
>       "apiKey": "your-api-key",
>       "apiBase": "https://api.your-provider.com",
>       "defaultModel": "your-model-name"
>     }
>   },
>   "modelPresets": {
>     "responsesProxy": {
>       "provider": "azure_openai",
>       "model": "your-model-name"
>     }
>   },
>   "agents": {
>     "defaults": {
>       "modelPreset": "responsesProxy"
>     }
>   }
> }
> ```
>
> Anthropic-compatible endpoint 是独立的：使用 `providers.anthropic.apiBase`，并将 preset provider 设置为 `anthropic`。任意自定义 provider 名称都不会使用 Anthropic Messages API 格式。
>
> 简而言之：**兼容 chat completions 的 endpoint → `custom` 或命名的 custom provider**；**兼容 Responses 的 endpoint → `azure_openai`**；**兼容 Anthropic 的 endpoint → 使用 `apiBase` 的 `anthropic`**。

某些 OpenAI-compatible gateway 会公开请求正文扩展，例如 vLLM 引导式解码或本地采样控制。将这些扩展放在 `extraBody` 下；nanobot 会在其 provider 默认值之后将它们合并到 chat-completions 请求正文中：

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1",
      "extraBody": {
        "repetition_penalty": 1.15,
        "chat_template_kwargs": {
          "enable_thinking": false
        }
      }
    }
  }
}
```
如果自定义的 OpenAI-compatible endpoint 提供 provider 特定的 thinking 开关，请设置 `thinkingStyle`，以便 nanobot 能将 `reasoningEffort` 转换为正确的请求体。支持的样式包括 `thinking_type`（`{"thinking":{"type":"enabled"}}`）、`enable_thinking`（`{"enable_thinking": true}`）和 `reasoning_split`（`{"reasoning_split": true}`）：

```json
{
  "providers": {
    "companyProxy": {
      "apiKey": "${COMPANY_PROXY_API_KEY}",
      "apiBase": "https://api.your-provider.com/v1",
      "thinkingStyle": "enable_thinking"
    }
  },
  "modelPresets": {
    "company": {
      "provider": "companyProxy",
      "model": "served-model-name",
      "reasoningEffort": "high"
    }
  }
}
```

除非 endpoint 明确文档说明使用上述某种 wire format，否则请不要设置 `thinkingStyle`。`extraBody` 仍会最后应用，因此高级用户可以覆盖生成的值。

</details>

<a id="local-providers"></a>
<a id="ollama-local"></a>
<details>
<summary><b>Ollama（本地）</b></summary>

使用 Ollama 运行本地 model，然后添加到 config：

**1. 启动 Ollama**（示例）：
```bash
ollama run llama3.2
```

**2. 添加到 config**（部分内容，合并到 `~/.nanobot/config.json`）：
```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434"
    }
  },
  "modelPresets": {
    "ollama": {
      "provider": "ollama",
      "model": "llama3.2"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "ollama"
    }
  }
}
```

> 配置 `providers.ollama.apiBase` 后，`provider: "auto"` 也可用，但在 preset 中固定 `"provider": "ollama"` 是最清晰的选择。

</details>

<details>
<summary><b>LM Studio（本地）</b></summary>

[LM Studio](https://lmstudio.ai/) 提供用于运行 LLM 的本地 OpenAI-compatible server。通过 LM Studio UI 下载 model，然后启动本地 server。

**1. 启动 LM Studio server：**
- 启动 LM Studio
- 转到“Local Server”标签页
- 加载一个 model（例如 Llama、Mistral、Qwen）
- 点击“Start Server”（默认端口：1234）

**2. 添加到 config**（部分内容，合并到 `~/.nanobot/config.json`）：
```json
{
  "providers": {
    "lm_studio": {
      "apiKey": null,
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "modelPresets": {
    "lmStudio": {
      "provider": "lm_studio",
      "model": "local-model"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "lmStudio"
    }
  }
}
```

> **注意：** 对于 LM Studio，请将 `apiKey` 设为 `null`，因为它在本地运行且不需要身份验证。model 名称应与 LM Studio UI 中显示的名称一致。配置 `providers.lm_studio.apiBase` 后，`provider: "auto"` 也可用，但在 preset 中固定 `"provider": "lm_studio"` 是最清晰的选择。

</details>

<a id="atomic-chat-local"></a>
<details>
<summary><b>Atomic Chat（本地）</b></summary>

[Atomic Chat](https://atomic.chat/) 是一个本地优先的桌面应用，提供 **OpenAI-compatible** HTTP API（默认 `http://localhost:1337/v1`）。当你希望让 nanobot 使用自己机器上的 model，而不是托管 API provider 时，可使用此设置。

**1. 启动 Atomic Chat**

- 在你的机器上安装 [Atomic Chat](https://atomic.chat/)。
- 打开 Atomic Chat，下载一个 model，并保持应用运行。本地 API 默认已启用。
- 复制本地 API 提供的 model ID。例如，`Qwen 3 32B` 的 model ID 可能是 `qwen3-32b`。

**2. 添加到 config**（部分内容，合并到 `~/.nanobot/config.json`）：

```json
{
  "providers": {
    "atomic_chat": {
      "apiKey": null,
      "apiBase": "http://localhost:1337/v1"
    }
  },
  "modelPresets": {
    "atomic": {
      "provider": "atomic_chat",
      "model": "qwen3-32b"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "atomic"
    }
  }
}
```

> **注意：** 将 `qwen3-32b` 替换为来自 Atomic Chat 的 model ID。如果你的 Atomic Chat server 不需要 key，请将 `apiKey` 设为 `null`。如果需要，请将 `apiKey`（或 `ATOMIC_CHAT_API_KEY` environment variable）设为 Atomic Chat 所要求的值。

> 配置 `providers.atomic_chat.apiBase` 后，`provider: "auto"` 也可用，但在 preset 中固定 `"provider": "atomic_chat"` 是最清晰的选择。

</details>

<details>
<summary><b>OpenVINO Model Server（本地 / OpenAI-compatible）</b></summary>

使用 [OpenVINO Model Server](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) 在 Intel GPU 上本地运行 LLM。OVMS 在 `/v3` 提供 OpenAI-compatible API。

> 需要 Docker，以及具有 driver 访问权限（`/dev/dri`）的 Intel GPU。

**1. 拉取 model**（示例）：

```bash
mkdir -p ov/models && cd ov

docker run -d \
  --rm \
  --user $(id -u):$(id -g) \
  -v $(pwd)/models:/models \
  openvino/model_server:latest-gpu \
  --pull \
  --model_name openai/gpt-oss-20b \
  --model_repository_path /models \
  --source_model OpenVINO/gpt-oss-20b-int4-ov \
  --task text_generation \
  --tool_parser gptoss \
  --reasoning_parser gptoss \
  --enable_prefix_caching true \
  --target_device GPU
```

> 这会下载 model 权重。继续之前请等待 container 完成。

**2. 启动 server**（示例）：

```bash
docker run -d \
  --rm \
  --name ovms \
  --user $(id -u):$(id -g) \
  -p 8000:8000 \
  -v $(pwd)/models:/models \
  --device /dev/dri \
  --group-add=$(stat -c "%g" /dev/dri/render* | head -n 1) \
  openvino/model_server:latest-gpu \
  --rest_port 8000 \
  --model_name openai/gpt-oss-20b \
  --model_repository_path /models \
  --source_model OpenVINO/gpt-oss-20b-int4-ov \
  --task text_generation \
  --tool_parser gptoss \
  --reasoning_parser gptoss \
  --enable_prefix_caching true \
  --target_device GPU
```

**3. 添加到 config**（部分内容，合并到 `~/.nanobot/config.json`）：

```json
{
  "providers": {
    "ovms": {
      "apiBase": "http://localhost:8000/v3"
    }
  },
  "modelPresets": {
    "ovms": {
      "provider": "ovms",
      "model": "openai/gpt-oss-20b"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "ovms"
    }
  }
}
```

> OVMS 是本地 server，无需 API key。支持 tool calling（`--tool_parser gptoss`）、reasoning（`--reasoning_parser gptoss`）和 streaming。更多详情请参阅[官方 OVMS 文档](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html)。
</details>

<a id="vllm-local-openai-compatible"></a>
<details>
<summary><b>vLLM（本地 / OpenAI-compatible）</b></summary>

使用 vLLM 或任何 OpenAI-compatible server 运行你自己的 model，然后添加到 config：

**1. 启动 server**（示例）：
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. 添加到 config**（部分内容，合并到 `~/.nanobot/config.json`）：

*Provider（本地 server 将 API key 设为 null）：*
```json
{
  "providers": {
    "vllm": {
      "apiKey": null,
      "apiBase": "http://localhost:8000/v1"
    }
  }
}
```

*Model preset：*
```json
{
  "modelPresets": {
    "vllm": {
      "provider": "vllm",
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "vllm"
    }
  }
}
```

</details>

关于添加新 provider 的贡献者说明位于 [`development.md`](development-zh.md#adding-an-llm-provider)。

## Model Presets

Model preset 可让你为完整的 model configuration 命名，并使用 `/model <preset>` 为每个 session 选择一个。它们是推荐的 model 配置方式，因为相同的名称可复用于新 session 默认值、chat-command 切换和 fallback chain。

现有 config 无需更改。直接设置的 `agents.defaults.model`、`provider`、`maxTokens`、`contextWindowTokens`、`temperature` 和 `reasoningEffort` 字段仍会定义隐式 `default` preset。对于新的 config，优先使用顶层 `modelPresets` 加上 `agents.defaults.modelPreset`。

```json
{
  "modelPresets": {
    "fast": {
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep", "localSmall"]
    }
  },
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "model": "gpt-4.1-mini",
      "provider": "openai",
      "maxTokens": 4096,
      "contextWindowTokens": 128000,
      "temperature": 0.2,
      "reasoningEffort": "low"
    },
    "deep": {
      "label": "Deep",
      "model": "claude-opus-4-5",
      "provider": "anthropic",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "reasoningEffort": "high"
    },
    "localSmall": {
      "label": "Local Small",
      "model": "llama3.2",
      "provider": "ollama",
      "maxTokens": 4096,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  }
}
```

`modelPresets` 是顶层对象。其下的 key（`fast`、`deep`、`coding` 等）是用户定义的 preset 名称。每个 preset 支持：

| 字段 | 说明 |
|-------|-------------|
| `label` | 可选的显示名称，显示在 model 列表中。 |
| `model` | 用于此 preset 的 model 名称。 |
| `provider` | Provider 名称，或使用 `"auto"` 进行 provider 自动检测。 |
| `maxTokens` | 最大 completion/output token 数。 |
| `contextWindowTokens` | 用于 prompt 构建和 consolidation 决策的 context window 大小。 |
| `temperature` | 采样 temperature。 |
| `reasoningEffort` | 可选的 reasoning/thinking 设置。provider 支持情况各不相同。 |

`default` 是保留名称，始终表示由直接 `agents.defaults.*` 字段构建的隐式 preset；请勿定义 `modelPresets.default`。在现有 config 中，使用 `/model default` 切换回这些直接字段。

设置 `agents.defaults.modelPreset`，以选择没有保存 model selection 的 session 所遵循的 preset。当 `modelPreset` 为 `null` 或被省略时，这类 session 将遵循直接 `agents.defaults.*` 字段中的隐式 `default` preset。`/model <preset>` 会在当前 session 中保存 override，因此后续 turn 会在 process 重启后仍保留该 preset，而其他 session 不受影响。该 command 不会将选择写回 `config.json`。
### 模型回退

`agents.defaults.fallbackModels` 定义了活动模型配置的有序故障转移链。主模型仍由 `agents.defaults.modelPreset` 选择；在较旧的配置中，则由直接 `agents.defaults.*` 字段隐式使用的 `default` 预设选择。

每个回退候选项可以是以下任一项：

- `modelPresets` 中的预设名称，例如 `"deep"`。这是推荐形式。系统会使用该预设完整的模型、provider、生成参数和上下文窗口配置。
- 内联回退对象，至少包含 `provider` 和 `model`。省略可选的 `maxTokens`、`contextWindowTokens` 和 `temperature` 字段时，它们会继承活动主配置中的值。`reasoningEffort` 不会继承；省略它可让该回退保持关闭 reasoning，或者为支持 reasoning 的模型显式设置它。

预设回退链：

```json
{
  "modelPresets": {
    "fast": {
      "model": "gpt-4.1-mini",
      "provider": "openai",
      "maxTokens": 4096,
      "contextWindowTokens": 128000,
      "temperature": 0.2
    },
    "deep": {
      "model": "claude-opus-4-5",
      "provider": "anthropic",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "reasoningEffort": "high"
    },
    "localSmall": {
      "model": "llama3.2",
      "provider": "ollama",
      "maxTokens": 4096,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep", "localSmall"]
    }
  }
}
```

字符串条目是预设名称，而不是原始模型名称。在上面的示例中，`"deep"` 表示 `modelPresets.deep`；nanobot 不会将其解释为 provider 模型 ID。修改预设会同时更新 `/model <preset>` 切换以及引用该预设的任何回退链。

内联回退对象：

```json
{
  "modelPresets": {
    "fast": {
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": [
        {
          "provider": "deepseek",
          "model": "deepseek-v4-pro",
          "maxTokens": 4096,
          "contextWindowTokens": 262144
        }
      ]
    }
  }
}
```

仅当某个回退不值得命名为可复用预设时，才使用内联对象。`fallbackModels` 应位于 `agents.defaults` 下，而不是单个 `modelPresets` 条目内。

当主 provider 在任何回答文本流式传输之前返回可回退的模型/provider 错误时，通常会执行故障转移。流停滞超时是恢复例外：如果 provider 已经发出部分回答文本，随后发生停滞，nanobot 会关闭当前流式片段，并在新片段中重试/执行故障转移。典型的回退情况包括超时、连接错误、5xx 服务器错误、429 速率限制、过载、身份验证/权限失败（例如凭据无效或已过期）以及配额/余额耗尽。对于请求格式错误、内容过滤/拒答，或上下文长度/消息格式错误，不会执行回退。

如果回退候选项使用更小的 `contextWindowTokens` 值，nanobot 会使用活动链中的最小窗口构建上下文，以便每个候选项都能接收相同的提示词。

## 转录设置

音频转录是一项共享能力，由聊天 channel 的语音消息和 WebUI 麦克风输入使用。聊天 channel 的语音消息会在进入 agent 之前自动转录。WebUI 麦克风输入会先转录到编辑器中，因此你可以在发送前编辑文本。

在顶层 `transcription` 部分下配置转录：

```json
{
  "transcription": {
    "enabled": true,
    "provider": "groq",
    "model": null,
    "language": null,
    "maxDurationSec": 120,
    "maxUploadMb": 25
  }
}
```

| 设置 | 默认值 | 描述 |
|---------|---------|-------------|
| `enabled` | `true` | 为聊天 channel 的语音消息和 WebUI 麦克风输入启用音频转录。 |
| `provider` | `"groq"` | 转录后端：`"groq"`、`"openai"`、`"openrouter"`、`"xiaomi_mimo"`、`"stepfun"` 或 `"assemblyai"`。 |
| `model` | provider 默认值 | 可选的转录模型覆盖值。Groq 默认为 `whisper-large-v3`，OpenAI 默认为 `whisper-1`，OpenRouter 默认为 `openai/whisper-1`，Xiaomi MiMo ASR 默认为 `mimo-v2.5-asr`，StepFun ASR 默认为 `stepaudio-2.5-asr`，AssemblyAI 默认为 `universal-3-pro,universal-2`。OpenRouter 的转录端点仅接受语音转文本模型，例如 `nvidia/parakeet-tdt-0.6b-v3`、`openai/whisper-1` 或 `openai/gpt-4o-transcribe`；聊天 LLM 会在那里被拒绝。AssemblyAI 接受以逗号分隔的模型回退列表。 |
| `language` | `null` | 可选的 ISO-639 语言提示，例如 `"en"`、`"zh"`、`"ko"` 或 `"ja"`。 |
| `maxDurationSec` | `120` | WebUI 录音的最大时长。 |
| `maxUploadMb` | `25` | WebUI 音频上传的最大大小。 |

出于向后兼容的考虑，provider 和 language 的解析顺序是固定的：

1. `transcription.provider` / `transcription.language`
2. 旧版 `channels.transcriptionProvider` / `channels.transcriptionLanguage`
3. 内置默认值（`provider: "groq"`，无 language 提示）

旧版 `channels.*` 转录字段早于转录成为聊天 channel 和 WebUI 麦克风输入之间的共享能力。系统仍会读取这些字段，以确保旧版 `config.json` 文件继续工作，但它们不再是首选配置入口。如果旧字段和新字段同时存在，则以顶层 `transcription` 值为准。

出于明确的设计考虑，转录凭据不会存储在 `transcription` 中。请将 API key 和可选 endpoint 放入对应的 provider 配置中：

```json
{
  "providers": {
    "groq": {
      "apiKey": "gsk-...",
      "apiBase": "https://api.groq.com/openai/v1"
    }
  },
  "transcription": {
    "provider": "groq",
    "language": "zh"
  }
}
```

选择转录 provider 本身不会配置凭据。例如，有效 provider 可能为了兼容性默认为 Groq，但只有在 `providers.groq.apiKey` 或匹配的基于环境变量的配置可用时，转录才可使用。Settings UI 只写入顶层 `transcription` 字段。

如果要添加新的转录 provider，请参阅 [`development.md`](development-zh.md#adding-a-transcription-provider)。

## Channel 设置

适用于所有 channel 的全局设置。在 `~/.nanobot/config.json` 的 `channels` 部分下配置：

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": true,
    "sendMaxRetries": 3,
    "telegram": {
      "enabled": false
    }
  }
}
```

| 设置 | 默认值 | 描述 |
|---------|---------|-------------|
| `sendProgress` | `true` | 将 agent 的文本进度流式传输到 channel |
| `sendToolHints` | `true` | 流式传输 tool 调用提示（例如 `read_file("…")`） |
| `showReasoning` | `true` | 允许 channel 展示模型 reasoning/thinking 内容（DeepSeek-R1 的 `reasoning_content`、Anthropic 的 `thinking_blocks`、内联 `<think>` 标签）。Reasoning 会作为独立流传输，并带有 `_reasoning_delta` / `_reasoning_end` 标记；channel 会覆盖 `send_reasoning_delta` / `send_reasoning_end`，以渲染原位更新。即使该值为 `true`，没有这些覆盖实现的 channel 也会静默保持 no-op。目前 CLI 和 WebSocket/WebUI 会展示该内容（斜体 shimmer 标题，流结束后自动折叠）；Telegram / Slack / Discord / Feishu / WeChat / Matrix / Mattermost 在其气泡 UI 适配完成前仍保持基础 no-op。独立于 `sendProgress`。 |
| `sendMaxRetries` | `3` | 每条出站消息的最大投递次数，包括初始发送（配置范围为 0-10，实际尝试次数至少为 1） |

非图像附件会以本地路径引用的形式包含在用户消息中，不会将其内容注入模型提示词。当文件 tool 启用时，agent 可以按需使用 `read_file` 检查受支持的文本、PDF、DOCX、XLSX 和 PPTX 文件，或者在需要精确文件字节时将原始路径传递给其他 tool。已弃用的 `channels.extractDocumentText` 设置会为兼容性而接受，但会被忽略。正常的 tool workspace 和媒体访问规则仍适用于附件路径。

`channels.transcriptionProvider` 和 `channels.transcriptionLanguage` 是已弃用的兼容字段。它们仍作为旧版配置的只读回退保留，但新配置应使用顶层的 `transcription.provider` 和 `transcription.language`。

也可以按 channel 覆盖 `sendProgress` 和 `sendToolHints`。对于未设置自身值的 channel，全局值仍作为默认值：

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": true,
    "telegram": {
      "enabled": true,
      "sendProgress": false,
      "sendToolHints": false
    },
    "websocket": {
      "enabled": true,
      "sendToolHints": true
    }
  }
}
```

Telegram `richMessages` 默认为 `false`。仅在需要选择使用 Bot API 10.1 `sendRichMessage` 渲染时启用它；对于会因富消息显示不支持消息错误的 Telegram Web 客户端，请保持禁用。

### 重试行为

重试机制有意保持简单。

当 channel 的 `send()` 抛出错误时，nanobot 会在 channel-manager 层重试。默认情况下，`channels.sendMaxRetries` 为 `3`，该次数包括初始发送。

- **尝试 1**：立即发送
- **尝试 2**：在 `1s` 后重试
- **尝试 3**：在 `2s` 后重试
- **更高的重试次数**：退避时间依次为 `1s`、`2s`、`4s`，之后保持上限 `4s`
- **暂时性失败**：网络短暂故障和临时 API 限制通常会在下一次尝试中恢复
- **永久性失败**：无效 token、访问权限被撤销或 channel 被封禁会耗尽重试次数，并干净地失败

> [!NOTE]
> 这一设计是有意为之：channel 实现应在投递失败时抛出错误，而 channel manager 负责共享的重试策略。
>
> 某些 channel 仍可能在内部应用少量特定于 API 的重试。例如，Telegram 会分别重试超时和洪泛控制错误，然后才向 manager 报告最终失败。
>
> 如果某个 channel 完全无法访问，nanobot 无法通过同一个 channel 通知用户。请查看日志中的 `Failed to send to {channel} after N attempts`，以发现持续的投递失败。
## Web 工具

nanobot 集成了用于访问 Web 的基本工具。这些工具包括通过 API 进行搜索，以及以 Markdown 格式获取任意网页。它们默认启用，可在 `~/.nanobot/config.json` 的 `tools.web` 下进行配置。

如果要禁用这些工具，这会同时从发送给 LLM 的工具列表中移除 `web_search` 和 `web_fetch`，请将 `tools.web.enable` 设置为 `false`：

```json
{
  "tools": {
    "web": {
      "enable": false
    }
  }
}
```

nanobot 对内置 Web 获取功能以及 HTTP/SSE MCP 连接使用共享的 SSRF 防护机制。默认情况下，它会阻止回环地址、RFC1918/私有地址段、CGNAT/Tailscale 地址段、链路本地地址和云元数据端点。如果需要允许受信任的私有地址段，请通过 `tools.ssrfWhitelist` 将其显式排除在 SSRF 阻止范围之外：

```json
{
  "tools": {
    "ssrfWhitelist": ["100.64.0.0/10"]
  }
}
```

白名单条目应尽可能精确，例如单个主机 CIDR（`192.168.1.50/32`）。该白名单对共享 SSRF 防护机制是全局的；它不局限于某个工具或某个 MCP server。

HTTP/SSE MCP 连接使用与 `web_fetch` 相同的进程级代理环境行为：经过代理的目标使用已配置的代理，而被 `NO_PROXY` 排除的 URL 则保持 DNS 固定的直接连接。

> [!TIP]
> 在 `tools.web` 中使用 `proxy`，可通过代理路由 Web 请求：
> ```json
> { "tools": { "web": { "proxy": "http://127.0.0.1:7890" } } }
> ```
> `web_fetch` 对直接连接应用 DNS 固定。当显式配置了 `tools.web.proxy`，或进程级代理环境变量适用于目标 URL 时，nanobot 仍会在本地验证请求的 URL，但出站获取请求的 DNS 解析会在代理处进行；请仅配置受信任的代理。被 `NO_PROXY` 排除的 URL 会继续使用 DNS 固定的直接路径，除非配置了 `tools.web.proxy`。

### `tools.web`

| 选项 | 类型 | 默认值 | 描述 |
|--------|------|---------|-------------|
| `enable` | boolean | `true` | 启用或禁用所有内置 Web 工具（`web_search` + `web_fetch`） |
| `proxy` | string 或 null | `null` | Web 请求使用的代理，例如 `http://127.0.0.1:7890`。`web_fetch` 的 DNS 固定仅适用于直接连接；经过代理的获取请求依赖已配置的代理作为受信任的网络出口。 |
| `userAgent` | string 或 null | `null` | 所有 Web 请求使用的 User-Agent 请求头。如果为 null，则使用浏览器 User-Agent |

### Web 搜索

nanobot 支持多个 Web 搜索 provider。在 `~/.nanobot/config.json` 的 `tools.web.search` 下进行配置。

默认情况下，Web 搜索使用 `duckduckgo`，无需 API key 即可开箱即用。

| Provider | 配置字段 | 环境变量回退值 | 免费 |
|----------|--------------|------------------|------|
| `brave` | `apiKey` | `BRAVE_API_KEY` | 否 |
| `tavily` | `apiKey` | `TAVILY_API_KEY` | 否 |
| `jina` | `apiKey` | `JINA_API_KEY` | 免费层（10M tokens） |
| `kagi` | `apiKey` | `KAGI_API_KEY` | 否 |
| `olostep` | `apiKey` | `OLOSTEP_API_KEY` | 否 |
| `bocha` | `apiKey` | `BOCHA_API_KEY` | 免费层（面向初创公司的 1M 次调用） |
| `volcengine` | `apiKey` | `VOLCENGINE_SEARCH_API_KEY` 或 `WEB_SEARCH_API_KEY` | 每月配额，用完后付费 |
| `keenable` | `apiKey`（可选） | `KEENABLE_API_KEY` | 是（无需 key；使用 key 可提高限制） |
| `searxng` | `baseUrl` | `SEARXNG_BASE_URL` | 是（自行托管） |
| `duckduckgo`（默认） | — | — | 是 |

**Brave：**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "${BRAVE_API_KEY}"
      }
    }
  }
}
```

**Tavily：**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "tavily",
        "apiKey": "${TAVILY_API_KEY}"
      }
    }
  }
}
```

**Jina**（免费层包含 10M tokens）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "jina",
        "apiKey": "${JINA_API_KEY}"
      }
    }
  }
}
```

**Kagi：**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "kagi",
        "apiKey": "${KAGI_API_KEY}"
      }
    }
  }
}
```

**Olostep：**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "olostep",
        "apiKey": "${OLOSTEP_API_KEY}"
      }
    }
  }
}
```

也可以在环境中设置 `OLOSTEP_API_KEY`，而不是将其存储在配置中。

**Bocha**（针对 AI 优化的搜索，提供免费层）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "bocha",
        "apiKey": "${BOCHA_API_KEY}"
      }
    }
  }
}
```

在 [open.bochaai.com](https://open.bochaai.com) 创建 API key。  
Bocha 返回针对 AI 消费进行优化的结构化结果，并支持可选的摘要。  
也可以在环境中设置 `BOCHA_API_KEY`，而不是将其存储在配置中。

**Volcengine Search：**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "volcengine",
        "apiKey": "${VOLCENGINE_SEARCH_API_KEY}"
      }
    }
  }
}
```

为了兼容 Volcengine Web 搜索 skill，也可以设置 `WEB_SEARCH_API_KEY`。在 [Volcengine Web 搜索控制台](https://console.volcengine.com/search-infinity/web-search)中创建 key，然后从 [API keys](https://console.volcengine.com/search-infinity/api-key) 中复制该 key。Volcengine Ark key 是独立的，不能用于此搜索 provider。

**Keenable**（免费层无需 API key 即可使用）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "keenable"
      }
    }
  }
}
```

Keenable 搜索无需账户即可开箱即用，通过其无需 token 的公共端点提供服务（免费层每小时最多 1,000 次请求）。从 [keenable.ai](https://keenable.ai) 设置 `apiKey`（或 `KEENABLE_API_KEY`），即可移除每小时限制。

**Serper**（Google Search API）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "serper",
        "apiKey": "${SERPER_API_KEY}"
      }
    }
  }
}
```

在 [serper.dev](https://serper.dev) 创建 key。也可以在环境中设置 `SERPER_API_KEY`，而不是将其存储在配置中。

**SearXNG**（自行托管，无需 API key）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "searxng",
        "baseUrl": "https://searx.example"
      }
    }
  }
}
```

**DuckDuckGo**（零配置）：
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

#### `tools.web.search`

| 选项 | 类型 | 默认值 | 描述 |
|--------|------|---------|-------------|
| `provider` | string | `"duckduckgo"` | 搜索后端：`brave`、`tavily`、`jina`、`kagi`、`olostep`、`bocha`、`volcengine`、`keenable`、`serper`、`searxng`、`duckduckgo` |
| `apiKey` | string | `""` | API 支持的搜索 provider 使用的 API key |
| `baseUrl` | string | `""` | SearXNG 的基础 URL |
| `maxResults` | integer | `5` | 每次搜索返回的结果数（1–10） |

### Web 获取

> [!TIP]
> 如果遇到 JS 工作量证明或 Cloudflare 验证码问题，请设置随机 User-Agent 并禁用 Jina Reader：
> ```json
> { "tools": { "web": { "userAgent": "Not-A-Browser", "fetch": { "useJinaReader": false } } } }
> ```

nanobot 默认使用第三方 API [Jina Reader](https://jina.ai/reader/) 将任意页面转换为 Markdown 格式，以便 LLM 轻松处理；如果前者失败，则使用基于 [readability-lxml](https://github.com/buriy/python-readability) 的本地回退方案。

如果始终希望使用本地转换，可以通过以下配置强制启用：

```json
{
  "tools": {
    "web": {
      "fetch": {
        "useJinaReader": false
      }
    }
  }
}
```

#### `tools.web.fetch`

| 选项 | 类型 | 默认值 | 描述 |
|--------|------|---------|-------------|
| `useJinaReader` | boolean | `true` | 如果为 true，则优先使用 Jina Reader，而不是本地转换 |

## 图像生成

图像生成在 `tools.imageGeneration` 下配置，并使用所选 provider 的 `providers.<name>` 配置块中的凭据。

有关 WebUI 使用方法、provider 示例、artifact 存储和故障排除，请参阅[图像生成](image-generation-zh.md)。

## MCP（Model Context Protocol）

> [!TIP]
> 配置格式兼容 Claude Desktop / Cursor。可以直接从任意 MCP server 的 README 中复制 MCP server 配置。

nanobot 支持 [MCP](https://modelcontextprotocol.io/)：连接外部 tool server，并将其作为原生 agent tool 使用。

将 MCP server 添加到 `config.json`：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

支持两种传输模式：

| 模式 | 配置 | 示例 |
|------|--------|---------|
| **Stdio** | `command` + `args` | 通过 `npx` / `uvx` 使用本地进程 |
| **HTTP** | `url` + `headers`（可选） | 远程端点（`https://mcp.example.com/sse`） |

> [!IMPORTANT]
> HTTP/SSE MCP URL 会在探测或连接前进行验证，并且每个发出的 MCP HTTP 请求都会在跟随重定向前再次验证。默认情况下会阻止 `localhost`、`127.0.0.1`、RFC1918/私有 IP、CGNAT/Tailscale 地址段、链路本地地址和云元数据端点。这可能导致之前正常工作的本地或私有 HTTP MCP 配置失效，直到通过 `tools.ssrfWhitelist` 显式允许该端点；建议使用单主机 CIDR，例如 `127.0.0.1/32`、`::1/128` 或 `192.168.1.50/32`。Stdio MCP server 不受影响。

对于响应缓慢的 server，使用 `toolTimeout` 覆盖默认的每次调用 30 秒超时：

```json
{
  "tools": {
    "mcpServers": {
      "my-slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

使用 `enabledTools` 仅从 MCP server 注册工具的子集：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file", "mcp_filesystem_write_file"]
      }
    }
  }
}
```

`enabledTools` 接受原始 MCP tool 名称（例如 `read_file`）或封装后的 nanobot tool 名称（例如 `mcp_filesystem_write_file`）。

- 省略 `enabledTools`，或将其设置为 `["*"]`，以注册所有 capabilities（tools、resources 和 prompts）。
- 将 `enabledTools` 设置为 `[]`，以不从该 server 注册任何 tools。由于 resources 和 prompts 没有按名称筛选功能，它们也会被跳过。
- 将 `enabledTools` 设置为非空名称列表，以仅注册指定的 tools；resources 和 prompts 不会被注册。

MCP tools 会在启动时自动发现并注册。LLM 可以将它们与内置 tools 一起使用，无需额外配置。
## 安全性

> [!TIP]
> 对于生产部署，请在配置中同时设置 `"restrictToWorkspace": true` 和 `"tools.exec.sandbox": "bwrap"`。`restrictToWorkspace` 启用 nanobot 的应用层 workspace 防护；`tools.exec.sandbox` 为 shell 命令提供进程级隔离。

关于 API 密钥、令牌和其他机密，请参阅[用于存储机密的环境变量](#environment-variables-for-secrets) — 避免将它们直接存储在 `config.json` 中。

> [!NOTE]
> 当受限 WebUI 聊天选择配置的 agent workspace 之外的项目时，该项目会成为常规文件和 shell 边界。Nanobot 会为内置 skills、agent workspace 的 `skills/` 目录以及准确的 agent `memory/history.jsonl` 文件添加特定 capability 的只读访问权限。相邻的 memory/profile 文件以及所有跨 workspace 写入仍会被拒绝。Agent 所有的 `SOUL.md` 和 `USER.md` 会直接组装到 model 上下文中；这不会授予 file tools 对 agent workspace 更广泛的访问权限。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 当为 `true` 时，为 workspace 感知的 tools 启用 nanobot 的应用层 workspace 防护。File tools 会将路径解析到活动 workspace 下；选定的内部根目录可以添加为只读或明确启用写入的根目录，媒体上传默认是只读的。Shell 执行会拒绝 workspace 外部的 `working_dir` 值，并执行尽力而为的命令路径检查，但这不是 OS sandbox。 |
| `tools.exec.sandbox` | `""` | Shell 命令的 sandbox 后端。设置为 `"bwrap"` 可将 exec 调用包装在 [bubblewrap](https://github.com/containers/bubblewrap) sandbox 中 — 进程只能看到 workspace（读写）和媒体目录（只读）；配置文件和 API 密钥会被隐藏。会自动为 file tools 启用 workspace 限制。**仅限 Linux** — 要求已安装 `bwrap`（`apt install bubblewrap`；Docker 镜像中已预装）。macOS 或 Windows 不可用（bwrap 依赖 Linux 内核命名空间）。 |
| `tools.exec.enable` | `true` | 当为 `false` 时，shell `exec` tool 完全不会注册。使用此选项可完全禁用 shell 命令执行。 |
| `tools.exec.timeout` | `60` | Shell 命令的默认硬超时时间（秒）。配置值可以超过单次调用的 tool 上限；对于受信任的长时间运行命令，设置为 `0` 可禁用硬超时。 |
| `tools.exec.pathPrepend` | `""` | 运行 shell 命令时要添加到 `PATH` 前面的额外目录。当已配置的 tools 应优先进行可执行文件查找时使用，例如 Python 虚拟环境的 `bin` 或 `Scripts` 目录。 |
| `tools.exec.pathAppend` | `""` | 运行 shell 命令时要添加到 `PATH` 末尾的额外目录（例如用于 `ufw` 的 `/usr/sbin`）。 |
| `tools.exec.sandboxRoBinds` | `[]` | 使用 `--ro-bind-try` 以只读方式绑定到 `"bwrap"` sandbox 中的额外绝对路径，例如当这些路径也位于 `pathPrepend`/`pathAppend` 中时的 `/home/user/.local/bin` 或 `/home/user/.cargo/bin`。仅在 bwrap 处于活动状态时，这些根目录也会被 shell 绝对路径防护所接受。只能绑定其内容可供 agent 命令安全读取的目录；与活动 workspace 相等或包含活动 workspace 的路径会被忽略，因此无法暴露其被屏蔽的父目录。 |
| `tools.exec.sandboxRwBinds` | `[]` | 使用 `--bind-try` 以读写方式绑定到 `"bwrap"` sandbox 中的额外绝对路径，用于受信任的 tool 缓存或临时目录。请谨慎使用：此处列出的路径会被有意设置为可由 sandbox 内 shell 命令写入。与活动 workspace 相等或包含活动 workspace 的路径会被忽略。 |
| `tools.webuiAllowRemotePackageInstall` | `false` | 当为 `false` 时，WebUI 只能从与 nanobot 在同一台机器上打开的浏览器中安装缺失的可选软件包。仅当受信任的远程管理员获准向此 nanobot 环境安装 Python 软件包时，才设置为 `true`。 |
| `tools.ssrfWhitelist` | `[]` | 共享 SSRF 防护所豁免的 CIDR 范围，该防护用于 web fetch 和 HTTP/SSE MCP 连接。优先使用精确的主机 CIDR，例如 `192.168.1.50/32`；宽泛的范围会增加 SSRF 暴露。 |
| `channels.*.allowFrom` | 省略 | 每个 channel 的访问控制。省略以使用仅配对模式；设置为 `["*"]` 以允许所有人；或列出特定用户 ID。详情请参阅[配对](#pairing)。 |

**Docker 安全性**：官方 Docker 镜像以非 root 用户（`nanobot`，UID 1000）运行，并预装 bubblewrap。默认的 `docker-compose.yml` 会删除所有 Linux capability，并保持 Docker 默认的 AppArmor/seccomp 配置文件启用。如果在 Docker 内启用 `"tools.exec.sandbox": "bwrap"`，请使用 `docker-compose.bwrap.yml` 作为额外覆盖配置启动 Compose，以便 bubblewrap 能够创建嵌套命名空间。


## 配对

配对允许用户通过简单的代码交换获得 bot 的访问权限 — 无需编辑配置。这既适用于新用户，也适用于从新 channel 连接的现有用户（例如，已经在 Telegram 上获批、现在正在设置 Discord 的用户）。

### 工作原理

1. 用户在支持配对的 channel 上向 bot 发送 DM，但尚未获批。这包括 Telegram、Discord、WeChat，以及 Slack 或 Mattermost 等将 DM policy 设置为 `allowlist` 的 channel。
2. Bot 回复一个配对代码（如 `ABCD-EFGH`），并告诉用户将其转发给你。
3. 你批准该代码：

```text
/pairing approve ABCD-EFGH
```

4. 用户现在可以正常与 bot 聊天。

配对仅适用于 **DM** — 群聊中的未获批用户会被静默忽略。

### 仅配对模式

默认情况下，如果你未设置 `allowFrom`，支持配对的 channel 会在未获批用户向 bot 发送 DM 时发出配对代码。这意味着你可以完全跳过 `allowFrom`，通过配对管理访问权限：

```json
{
  "channels": {
    "telegram": {
      "enabled": true
    }
  }
}
```

Slack 和 Mattermost 的 DM 默认开放。要在那里使用配对，请将 channel 的 `dm.policy` 设置为 `"allowlist"`，并在批准用户之前将 `dm.allowFrom` 留空：

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "dm": { "policy": "allowlist" }
    }
  }
}
```

如果你更愿意允许所有人而无需批准：

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "allowFrom": ["*"]
    }
  }
}
```

### 管理访问权限

| 命令 | 作用 |
|---------|-------------|
| `/pairing` | 显示所有待处理的配对请求 |
| `/pairing approve <code>` | 批准请求 — 发送者现在可以聊天 |
| `/pairing deny <code>` | 拒绝待处理的请求 |
| `/pairing revoke <user_id>` | 从当前 channel 移除之前已批准的用户 |
| `/pairing revoke <channel> <user_id>` | 从指定 channel 移除用户 |

你可以在 `/pairing list` 的输出中找到用户 ID。

从终端执行：

```bash
nanobot agent -m "/pairing list"
nanobot agent -m "/pairing approve ABCD-EFGH"
```


## Gateway 心跳

Gateway 可以运行一个受保护的 heartbeat cron job，定期检查活动 workspace 中的 `HEARTBEAT.md`。运行 `nanobot gateway` 时默认启用此功能。

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800,
      "keepRecentMessages": 8
    }
  }
}
```

如果 `HEARTBEAT.md` 在 `## Active Tasks` 下包含任务，agent 会执行这些任务，并仅将有用/可操作的结果发送到最近活跃的 chat target。如果文件没有活动任务，或者结果属于例行结果且没有有用信息要报告，则 heartbeat 会被静默跳过。

这与用户创建的 cron job 有意不同。使用 `cron` tool 创建的 cron job 会在其源 chat/session 中作为计划 turn 运行，并通常将结果发送回该 channel。对于不应在每次运行时通知用户的定期后台检查，请使用 `HEARTBEAT.md`。

Heartbeat job 使用与用户创建的提醒相同的 cron service。它存储在活动 workspace（`<workspace>/cron/jobs.json`）下，并会在 `cron(action="list")` 中以 `heartbeat` 的形式显示，但它由系统管理，无法使用 `cron` tool 删除。如果不希望进行定期 heartbeat 检查，请通过配置禁用它并重启 gateway。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `gateway.heartbeat.enabled` | `true` | 在 gateway 启动时注册内置 heartbeat cron job。 |
| `gateway.heartbeat.intervalS` | `1800` | heartbeat 检查之间的秒数。 |
| `gateway.heartbeat.keepRecentMessages` | `8` | 每次运行后保留的最近 heartbeat-session 消息数量。 |
| `gateway.restartMode` | `auto` | `/restart` 的重启策略：`auto` 在 Windows 前台运行时使用 `spawn`，在其他情况下使用 `exec`。对于 WinSW 或 nssm 等 Windows service wrapper，请使用 `exit`，以便由 service manager 负责重启。 |

### 自定义 heartbeat evaluator prompt

通知 gate 基于内置 system prompt 运行。高级用户可以覆盖它，但通常不需要这样做 — 强烈建议先阅读 evaluator 代码和默认的 `evaluator.md`。要覆盖它，请将 prompt 放置在 `<workspace>/prompts/evaluator.md`。其中仍必须指示 model 调用 `evaluate_notification` tool；否则 gate 会默认拒绝并保持静默。


## Subagent 并发

默认情况下，nanobot 一次只允许一个已 spawn 的 subagent 运行。达到上限时，`spawn` tool 会返回错误，以便 agent 决定等待或重新安排工作。这可以防止本地 LLM server 同时加载多个 KV 缓存。如果你的 provider 能够处理更多并行工作，请提高上限：

```json
{
  "agents": {
    "defaults": {
      "maxConcurrentSubagents": 2
    }
  }
}
```

当 subagent 的某个 tool 返回执行错误时，subagent 也会立即停止。此默认行为可以让父 agent 看到失败。如果你的 subagent 工作流使用的 tools 可能暂时失败，并且应由 model 重试或采取变通措施，请禁用硬停止行为：

```json
{
  "agents": {
    "defaults": {
      "failOnToolError": false
    }
  }
}
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `agents.defaults.maxConcurrentSubagents` | `1` | 可同时运行的已 spawn subagent 的最大数量。超过此限制的 spawn 尝试会返回错误。 |
| `agents.defaults.failOnToolError` | `true` | 当 tool 执行失败时停止已 spawn 的 subagent。设置为 `false` 可将 tool 错误返回给 subagent model，使其能够在同一次运行中恢复。 |
## 自动压缩

当用户空闲时间超过配置的阈值时，nanobot 会**主动**将会话上下文中较早的部分压缩为摘要，同时保留最近一段有效的实时消息后缀。用户返回时，这可以降低 token 成本和首 token 延迟：模型无需使用已过期的 KV 缓存重新处理一段很长的陈旧上下文，而是会收到紧凑摘要、最近的实时上下文以及新输入。

```json
{
  "agents": {
    "defaults": {
      "idleCompactAfterMinutes": 15,
      "idleCompactCheckIntervalSeconds": 60
    }
  }
}
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `agents.defaults.idleCompactAfterMinutes` | `15` | 自动压缩开始前的空闲时间（分钟）。设置为 `0` 可禁用。默认值接近典型 LLM KV 缓存的过期窗口，因此陈旧会话会在用户返回前完成压缩。 |
| `agents.defaults.idleCompactCheckIntervalSeconds` | `60` | 扫描空闲会话之间的最短间隔秒数。设置为 `0` 可在每次空闲 tick（约 1 秒）时扫描。 |

为保持向后兼容性，`sessionTtlMinutes` 仍作为旧版别名接受，但今后推荐使用 `idleCompactAfterMinutes` 配置键。

工作方式：
1. **空闲检测**：每次空闲 tick（约 1 秒）时，检查是否需要进行空闲会话扫描。默认情况下，完整扫描最多每分钟运行一次。
2. **后台压缩**：空闲会话通过 LLM 总结较早的实时前缀，并保留最近的有效后缀（目前为 8 条消息）。
3. **注入摘要**：用户返回时，摘要会与保留的最近后缀一起作为运行时上下文注入（仅一次，不会持久化）。
4. **安全重启恢复**：摘要还会同步到会话元数据中，因此进程重启后仍可恢复。

> [!NOTE]
> 心智模型：“总结较早的上下文，保留最新的实时轮次，**并使用紧凑形式覆盖会话文件。**”这不是完整的 `session.clear()`，但它会写入文件，而不是仅移动软光标。
>
> 具体来说，自动压缩会原地重写 `sessions/<key>.jsonl`：较早的消息（包括其结构化的 `tool_calls` / `tool_call_id` / `reasoning_content`）会被替换为保留的最近后缀（目前为 8 条消息），而归档的前缀只会作为纯文本摘要追加到 `memory/history.jsonl` 中（如果 LLM 摘要失败，则追加 `[RAW] ...` 展平转储）。这些轮次的原始结构化 JSON 将无法再从会话文件中恢复。
>
> 这不同于当 prompt 超出上下文预算时触发的**由 token 驱动的软整合**：该路径只会推进内部的 `last_consolidated` 光标，不会修改会话文件，因此原始工具调用轨迹仍保留在磁盘上，之后仍可重放或审计。如果你依赖该轨迹进行调试或审计，请将 `idleCompactAfterMinutes` 设置为 `0`，仅让由 token 驱动的路径运行。

## 时区

时间是上下文。上下文应当精确。

默认情况下，nanobot 使用 `UTC` 作为运行时的时间上下文。如果你希望 agent 使用本地时间进行思考，请将 `agents.defaults.timezone` 设置为有效的 [IANA 时区名称](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)：

```json
{
  "agents": {
    "defaults": {
      "timezone": "Asia/Shanghai"
    }
  }
}
```

这会影响向模型显示的运行时时间字符串，例如运行时上下文。当 cron 表达式省略 `tz` 时，它也会成为 cron 调度的默认时区；当 ISO datetime 不包含显式偏移量时，它还会成为一次性 `at` 时间的默认时区。

常见示例：`UTC`、`America/New_York`、`America/Los_Angeles`、`Europe/London`、`Europe/Berlin`、`Asia/Tokyo`、`Asia/Shanghai`、`Asia/Singapore`、`Australia/Sydney`。

> 需要其他时区？请浏览完整的 [IANA 时区数据库](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)。

## 统一会话

默认情况下，每个 channel × chat ID 组合都会获得自己的会话。如果你在多个 channel（例如 Telegram + Discord + CLI）中使用 nanobot，并希望它们共享同一个对话，请启用 `unifiedSession`：

```json
{
  "agents": {
    "defaults": {
      "unifiedSession": true
    }
  }
}
```

启用后，所有传入消息都会被路由到同一个共享会话中，无论它们来自哪个 channel。从 Telegram 切换到 Discord（或其他 channel）时，对话都会无缝延续。

| 行为 | `false`（默认） | `true` |
|----------|-------------------|--------|
| 会话键 | `channel:chat_id` | `unified:default` |
| 跨 channel 连续性 | 否 | 是 |
| `/new` 清除范围 | 当前 channel 会话 | 共享会话 |
| `/stop` 查找任务 | 按 channel 会话 | 按共享会话 |
| 已存在的 `session_key_override`（例如 Telegram thread） | 遵循设置 | 仍然遵循设置，不会被覆盖 |

> 此功能面向单用户、多设备设置。它**默认关闭**，现有用户的行为不会发生任何变化。

## 已禁用技能

nanobot 自带内置技能，你的 workspace 也可以在 `skills/` 下定义自定义技能。如果你希望对 agent 隐藏特定技能，请将 `agents.defaults.disabledSkills` 设置为技能目录名称列表：

```json
{
  "agents": {
    "defaults": {
      "disabledSkills": ["github", "weather"]
    }
  }
}
```

已禁用的技能不会出现在主 agent 的技能摘要、始终启用的技能注入以及子 agent 的技能摘要中。当某些捆绑技能对于你的部署没有必要，或不应向终端用户公开时，此选项非常有用。

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `agents.defaults.disabledSkills` | `[]` | 要排除加载的技能目录名称列表。适用于内置技能和 workspace 技能。 |

## 工具提示最大长度

工具提示是 agent 调用工具时显示的简短进度消息（例如 `$ cd …/project && npm test`）。默认情况下，这些消息会截断为 40 个字符，这可能导致较长的命令难以阅读。

设置 `agents.defaults.toolHintMaxLength` 可控制截断阈值：

```json
{
  "agents": {
    "defaults": {
      "toolHintMaxLength": 120
    }
  }
}
```

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `agents.defaults.toolHintMaxLength` | `40` | 工具提示显示的最大字符数。范围：20–500。值越高，显示的命令或路径越多；值越低，提示越紧凑。 |
