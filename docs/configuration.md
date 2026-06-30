# Configuration

Config file: `~/.nanobot/config.json`

This is the full reference. If this is your first install, start with [`quick-start.md`](./quick-start.md). If you are trying to choose a model or fix provider/model matching, use [`providers.md`](./providers.md) first and come back here for exact fields and advanced options.

The JSON examples below are usually partial snippets to merge into your existing config, not full replacement files. For the mental model behind config, workspace, gateway, channels, sessions, tools, and memory, see [`concepts.md`](./concepts.md).

The generated `config.json` uses camelCase keys such as `apiKey` and `intervalS`. snake_case keys are also accepted for compatibility, but the docs prefer camelCase because that is what nanobot writes back to disk.

For setup and runtime failures, follow the diagnosis order in [`troubleshooting.md`](./troubleshooting.md) before changing multiple config areas at once.

> [!NOTE]
> If your config file is older than the current schema, you can refresh it without overwriting your existing values: run `nanobot onboard`, then answer `N` when asked whether to overwrite the config. nanobot will merge in missing default fields and keep your current settings.

## Quick Jump

| Need | Section |
|---|---|
| Keep secrets out of `config.json` | [Environment Variables for Secrets](#environment-variables-for-secrets) |
| Tune process-level behavior with env vars | [Runtime Environment Variables](#runtime-environment-variables) |
| Trace model calls | [Langfuse Observability](#langfuse-observability) |
| Configure credentials and endpoints | [Providers](#providers) |
| Name and switch model choices | [Model Presets](#model-presets) |
| Add fallback chains | [Model Fallbacks](#model-fallbacks) |
| Configure voice transcription | [Transcription Settings](#transcription-settings) |
| Tune channel defaults | [Channel Settings](#channel-settings) |
| Configure web search and fetch | [Web Tools](#web-tools) |
| Enable image generation | [Image Generation](#image-generation) |
| Add MCP servers | [MCP](#mcp-model-context-protocol) |
| Review shell, workspace, and SSRF controls | [Security](#security) |
| Control access and pairing | [Pairing](#pairing) |
| Tune gateway jobs, sessions, and tools | [Gateway Heartbeat](#gateway-heartbeat), [Auto Compact](#auto-compact), [Unified Session](#unified-session), [Tool Hint Max Length](#tool-hint-max-length) |

## Where to Edit First

If you are not sure where a setting belongs, start from the task you are trying to complete. Most changes touch one config section and one verification command.

| Task | First keys to check | Verify with | Deep dive |
|---|---|---|---|
| Make the first model reply work | `providers.<name>.apiKey`, optional `providers.<name>.apiBase`, `modelPresets.<preset>`, `agents.defaults.modelPreset` | `nanobot status`, then `nanobot agent -m "Hello!"` | [Providers](#providers), [Model Presets](#model-presets) |
| Add fallback models | `modelPresets.<fallback>`, `agents.defaults.fallbackModels` | `nanobot status`, then a normal agent run | [Model Fallbacks](#model-fallbacks) |
| Keep secrets out of the config file | `${ENV_VAR}` placeholders inside any string value | Start nanobot from the same environment that sets the variable | [Environment Variables for Secrets](#environment-variables-for-secrets) |
| Open the bundled WebUI | `channels.websocket.enabled`, optional `channels.websocket.port`, `channels.websocket.tokenIssueSecret` | `nanobot gateway`, then open `http://127.0.0.1:8765` | [Channel Settings](#channel-settings), [WebSocket docs](./websocket.md) |
| Connect one chat app | `channels.<channel>.enabled`, channel credentials, `channels.<channel>.allowFrom` | `nanobot channels status`, then `nanobot gateway --verbose` | [Channel Settings](#channel-settings), [Chat Apps](./chat-apps.md) |
| Enable voice transcription | `transcription.enabled`, `transcription.provider`, matching `providers.<name>.apiKey` | Send or upload a short voice message through a configured surface | [Transcription Settings](#transcription-settings) |
| Enable web search or fetch | `tools.web.search.*`, `tools.web.fetch.*`, optional `tools.ssrfWhitelist` | Ask a question that requires current web information, then inspect logs if needed | [Web Tools](#web-tools), [Security](#security) |
| Enable image generation | `tools.imageGeneration.enabled`, `tools.imageGeneration.provider`, `tools.imageGeneration.model`, matching provider credentials | Enable Image Generation in the WebUI and send one image request | [Image Generation](#image-generation) |
| Add external tools through MCP | `tools.mcpServers.<name>` | Start `nanobot gateway --verbose` and check startup/tool logs | [MCP](#mcp-model-context-protocol) |
| Tighten tool and network safety | `tools.restrictToWorkspace`, `tools.exec.sandbox`, `tools.ssrfWhitelist`, `channels.*.allowFrom` | Run the same workflow through the channel or CLI you plan to expose | [Security](#security), [Pairing](#pairing) |
| Tune request timeouts or process concurrency | `NANOBOT_LLM_TIMEOUT_S`, `NANOBOT_STREAM_IDLE_TIMEOUT_S`, `NANOBOT_MAX_CONCURRENT_REQUESTS` | Start nanobot from the same environment and inspect startup/runtime logs | [Runtime Environment Variables](#runtime-environment-variables) |
| Run multiple isolated bots | separate `--config` and `--workspace` paths, plus distinct `gateway.port` or channel ports when processes run together | Start each process with explicit paths and run `nanobot status` for the default instance only | [Multiple Instances](./multiple-instances.md), [CLI Reference](./cli-reference.md) |
| Observe model calls | `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL` environment variables | Run one model call, then check the matching Langfuse project | [Langfuse Observability](#langfuse-observability) |

## Environment Variables for Secrets

Instead of storing secrets directly in `config.json`, you can use `${VAR_NAME}` references that are resolved from environment variables at startup:

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

Any string value in `config.json` can use `${VAR_NAME}`. Resolution runs once at startup, in memory only — resolved values are never written back to disk, so editing config through `nanobot onboard` or the WebUI preserves the placeholder.

If a referenced variable is unset, nanobot fails fast at startup with `ValueError: Environment variable 'NAME' referenced in config is not set`.

### More examples

**MCP servers** — both stdio `env` and HTTP `headers`:

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

**Web search providers:**

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

### Loading variables at startup

Pick whatever fits your deployment — nanobot only reads `os.environ` at startup, so any mechanism that populates the process environment works.

**systemd** — use `EnvironmentFile=` in the service unit to load variables from a file that only the deploying user can read:

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

**Docker** — pass an env file to the locally built image (one `KEY=VALUE` per line), or use `-e KEY=value`:

```bash
docker run --rm --env-file=./nanobot.env \
  -v ~/.nanobot:/home/nanobot/.nanobot \
  nanobot agent -m "Hello"
```

**direnv** — drop a `.envrc` in your working directory and run `direnv allow`:

```bash
# .envrc (auto-loaded by direnv)
export TELEGRAM_TOKEN=your-token-here
export ANTHROPIC_API_KEY=...
```

**Secret managers (1Password, Bitwarden, pass)** — wrap the process so secrets only exist as env vars for the lifetime of the run, never on disk:

```bash
# 1Password — references in .env.tpl look like `op://Vault/Item/field`
op run --env-file=.env.tpl -- nanobot agent

# pass (passwordstore.org)
ANTHROPIC_API_KEY="$(pass show api/anthropic)" nanobot agent

# Bitwarden
ANTHROPIC_API_KEY="$(bw get password api/anthropic)" nanobot agent
```

## Runtime Environment Variables

These variables are process-level switches. Set them in the same terminal, service unit, container, or supervisor that starts nanobot.

### Runtime controls

| Variable | Default | Description |
|----------|---------|-------------|
| `NANOBOT_MAX_CONCURRENT_REQUESTS` | `3` | Maximum concurrently running inbound agent requests. Must be an integer; set `0` or a negative value for unlimited. |
| `NANOBOT_LLM_TIMEOUT_S` | `300` | Wall-clock timeout, in seconds, around ordinary LLM requests. Set `0` to disable. Sustained-goal turns bypass this wall-clock cap. |
| `NANOBOT_STREAM_IDLE_TIMEOUT_S` | `90` | Streaming idle timeout, in seconds, used by streaming providers. Invalid or non-positive values are ignored; values above `3600` are clamped. |
| `NANOBOT_OPENAI_COMPAT_TIMEOUT_S` | `120` | HTTP request timeout, in seconds, for OpenAI-compatible providers. Invalid or non-positive values are ignored. |
| `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` | unset | Marks that an external workspace sandbox is already enforced. Truthy values (`1`, `true`, `yes`, `on`, `enabled`) use `NANOBOT_WORKSPACE_SANDBOX_PROVIDER` as the label; any other non-false value is treated as the provider name. |
| `NANOBOT_WORKSPACE_SANDBOX_PROVIDER` | `unknown` | Display label for the external workspace sandbox when `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` is truthy, for example `macos_app_sandbox` or `bwrap`. |
| `NANOBOT_SANDBOX_ENFORCED` | unset | Legacy compatibility alias for `NANOBOT_WORKSPACE_SANDBOX_ENFORCED`. |
| `NANOBOT_TMUX_SOCKET_DIR` | `${TMPDIR:-/tmp}/nanobot-tmux-sockets` | Socket directory used by the bundled `tmux` skill scripts. |

### Installer, build, and WebUI development

| Variable | Default | Description |
|----------|---------|-------------|
| `NANOBOT_BIN_DIR` | `$HOME/.local/bin` | Installer launcher directory on macOS/Linux. |
| `NANOBOT_VENV` | `$HOME/.nanobot/venv` | Managed virtual environment path used by the installer fallback. |
| `NANOBOT_SKIP_WIZARD` | unset | Set to `1` to skip `nanobot onboard --wizard` after one-command install. |
| `NANOBOT_SKIP_WEBUI_BUILD` | unset | Set to `1` to skip bundling the WebUI during package builds. |
| `NANOBOT_FORCE_WEBUI_BUILD` | unset | Set to `1` to rebuild the bundled WebUI even when `nanobot/web/dist/index.html` already exists. |
| `NANOBOT_API_URL` | `http://127.0.0.1:8765` | Gateway target for the Vite WebUI dev server proxy. |

Internal variables such as `NANOBOT_RESTART_*` and `NANOBOT_PATH_*` are set by nanobot itself and are not a supported user configuration surface.

## Langfuse Observability

nanobot can trace OpenAI-compatible provider calls through Langfuse's OpenAI SDK wrapper. This is configured with environment variables, not `config.json`.

Install the optional package in the same Python environment that runs nanobot:

```bash
python -m pip install langfuse
```

Set Langfuse credentials before starting `nanobot agent`, `nanobot gateway`, or `nanobot serve`:

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
```

For PowerShell:

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
```

When `LANGFUSE_SECRET_KEY` is set and the `langfuse` package is installed, nanobot uses `langfuse.openai.AsyncOpenAI` for OpenAI-compatible providers so model requests are sent to Langfuse in the background. If the secret key is set but `langfuse` is missing, nanobot logs a warning and falls back to the regular OpenAI client.

Use the Langfuse region or self-hosted URL that matches your project. The [Langfuse OpenAI SDK docs](https://langfuse.com/integrations/model-providers/openai-py) use `LANGFUSE_BASE_URL` for cloud regions and self-hosted instances.

Tracing covers the providers that go through nanobot's OpenAI-compatible client path. Native providers that do not use that client may not produce Langfuse OpenAI-wrapper traces.

## Providers

> [!TIP]
> - **Voice transcription**: Voice messages and WebUI microphone input use the shared top-level `transcription` settings. The default `transcription.provider` value is `"groq"`; set it to `"openai"` for OpenAI Whisper, `"openrouter"` for OpenRouter speech-to-text models, `"xiaomi_mimo"` for Xiaomi MiMo ASR, or `"assemblyai"` for AssemblyAI. API keys still live in the matching `providers.<provider>` config.
> - **MiniMax Coding Plan**: Exclusive discount links for the nanobot community: [Overseas](https://platform.minimax.io/subscribe/coding-plan?code=9txpdXw04g&source=link) · [Mainland China](https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link)
> - **MiniMax (Mainland China)**: If your API key is from MiniMax's mainland China platform (minimaxi.com), set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **MiniMax thinking mode**: `providers.minimaxAnthropic` is the config block for `reasoningEffort` / thinking mode. MiniMax exposes that capability through its Anthropic-compatible endpoint, so nanobot keeps it as a separate provider instead of guessing MiniMax-specific thinking parameters on the generic OpenAI-compatible `minimax` endpoint. It uses the same `MINIMAX_API_KEY`. Default Anthropic-compatible base URL: `https://api.minimax.io/anthropic`; for mainland China use `https://api.minimaxi.com/anthropic`.
> - **Kimi Coding Plan**: Use `providers.kimiCoding` with `provider: "kimi_coding"` for Kimi's dedicated Anthropic Messages API endpoint. The endpoint requires a Claude-compatible `User-Agent`; nanobot sends `claude-code/0.1.0` by default, and you can override it with `extraHeaders.User-Agent` if your account requires a different value.
> - **VolcEngine / BytePlus Coding Plan**: Subscription endpoints are configured through dedicated providers `volcengineCodingPlan` or `byteplusCodingPlan`, separate from the pay-per-use `volcengine` / `byteplus` providers.
> - **OpenCode Zen / Go**: `providers.opencodeZen` and `providers.opencodeGo` use the same `OPENCODE_API_KEY`, but route to different OpenCode gateways. These providers use OpenCode's OpenAI-compatible `chat/completions` endpoints; choose model IDs from that endpoint family.
> - **Zhipu Coding Plan**: If you're on Zhipu's coding plan, set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **Alibaba Cloud BaiLian**: If you're using Alibaba Cloud BaiLian's OpenAI-compatible endpoint, set `"apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"` in your dashscope provider config.
> - **StepFun Step Plan**: If you're on StepFun's Step Plan subscription, set `"apiBase": "https://api.stepfun.ai/step_plan/v1"` in your stepfun provider config. Supported models include `step-3.5-flash`, `step-3.5-flash-2603`, and `step-router-v1`.
> - **Step Fun (Mainland China)**: If your API key is from Step Fun's mainland China platform (stepfun.com), set `"apiBase": "https://api.stepfun.com/v1"` in your stepfun provider config.
> - **Xiaomi MiMo thinking mode**: MiMo models (e.g. `mimo-v2.5-pro`) default to enabled thinking. Use `agents.defaults.reasoningEffort: "none"` to disable it, or `"low"` / `"medium"` / `"high"` to keep it on. Omitting the field preserves the provider's per-model default.
> - **Xiaomi MiMo Token Plan**: If you're on MiMo's token plan, set `"apiBase": "https://token-plan-sgp.xiaomimimo.com/v1"` in your xiaomi_mimo provider config.
> - **Custom OpenAI-compatible providers**: Besides the built-in `custom` provider, any extra key under `providers` can define its own OpenAI-compatible endpoint. For example, `providers.companyProxy.apiBase` plus `modelPresets.primary.provider: "companyProxy"` creates a separate custom provider. Set `apiBase`; set `apiKey` only when the endpoint requires it. This named-custom path uses the OpenAI-compatible request format only. For Anthropic-compatible proxies, use `providers.anthropic.apiBase` with `provider: "anthropic"`.
> - **Provider-scoped proxy**: `providers.<name>.proxy` routes only that provider through an HTTP proxy. It is supported for OpenAI-compatible providers and `openai_codex`. Native provider backends such as `anthropic`, `bedrock`, `azure_openai`, and `github_copilot` reject `proxy`.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint | — |
| `openrouter` | LLM gateway for hosted model families + Voice transcription (STT models) | [openrouter.ai](https://openrouter.ai) |
| `opencode_zen` | LLM gateway (OpenCode Zen coding-agent models) | [opencode.ai/docs/zen](https://opencode.ai/docs/zen/) |
| `opencode_go` | LLM gateway (OpenCode Go low-cost coding models) | [opencode.ai/docs/go](https://opencode.ai/docs/go/) |
| `huggingface` | LLM (Hugging Face Inference Providers) | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `skywork` | LLM (Skywork / APIFree API gateway) | [apifree.ai](https://www.apifree.ai) |
| `volcengine` | LLM (VolcEngine, pay-per-use) | [Coding Plan](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [volcengine.com](https://www.volcengine.com) |
| `volcengine_coding_plan` | LLM (VolcEngine Coding Plan subscription endpoint) | [volcengine.com](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) |
| `byteplus` | LLM (VolcEngine international, pay-per-use) | [Coding Plan](https://www.byteplus.com/en/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [byteplus.com](https://www.byteplus.com) |
| `byteplus_coding_plan` | LLM (BytePlus Coding Plan subscription endpoint) | [byteplus.com](https://www.byteplus.com/en/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM (Azure OpenAI) | [portal.azure.com](https://portal.azure.com) |
| `bedrock` | LLM (AWS Bedrock Converse, Claude/Nova/Llama/etc.) | [aws.amazon.com/bedrock](https://aws.amazon.com/bedrock/) |
| `openai` | LLM + Voice transcription (Whisper) | [platform.openai.com](https://platform.openai.com) |
| `assemblyai` | Voice transcription only | [assemblyai.com](https://www.assemblyai.com/) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + Voice transcription (Whisper, default) | [console.groq.com](https://console.groq.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `minimax_anthropic` | LLM (MiniMax Anthropic-compatible endpoint, thinking mode) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM (API gateway, access to all models) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `novita` | LLM (Novita AI OpenAI-compatible gateway) | [novita.ai](https://novita.ai) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.kimi.com](https://platform.kimi.com?aff=nanobot) |
| `kimi_coding` | LLM (Kimi Coding Plan, Anthropic Messages API) | [platform.kimi.com](https://platform.kimi.com?aff=nanobot) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `xiaomi_mimo` | LLM (MiMo) | [platform.xiaomimimo.com](https://platform.xiaomimimo.com) |
| `longcat` | LLM (LongCat) | [longcat.chat](https://longcat.chat/platform/docs/zh/) |
| `ant_ling` | LLM (Ant Ling / 蚂蚁百灵) | [developer.ant-ling.com](https://developer.ant-ling.com/en/docs/api-reference/openai/) |
| `ollama` | LLM (local, Ollama) | — |
| `lm_studio` | LLM (local, LM Studio) | — |
| `atomic_chat` | LLM (local, [Atomic Chat](https://atomic.chat/)) | — |
| `mistral` | LLM | [docs.mistral.ai](https://docs.mistral.ai/) |
| `stepfun` | LLM (Step Fun/阶跃星辰) + Voice transcription (ASR) | [platform.stepfun.com](https://platform.stepfun.com) |
| `ovms` | LLM (local, OpenVINO Model Server) | [docs.openvino.ai](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |
| `nvidia` | LLM (NVIDIA NIM) | [build.nvidia.com](https://build.nvidia.com/) |
| `openai_codex` | LLM (Codex, OAuth) | `nanobot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |
| `qianfan` | LLM (Baidu Qianfan) | [cloud.baidu.com](https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26) |

<details>
<summary><b>OpenAI</b></summary>

By default, OpenAI uses `apiType: "auto"`: nanobot calls Chat Completions normally and routes GPT-5/o-series or explicit `reasoningEffort` requests through the Responses API when useful. You can force a specific API surface:

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

Valid `apiType` values are exactly `auto`, `chat_completions`, and `responses`.

`extraBody` follows the selected OpenAI API surface. With Chat Completions, nanobot passes it through as the SDK `extra_body` value. With Responses, configure it in Responses API body shape; nanobot merges ordinary top-level fields into the Responses request body, appends `extraBody.tools` after generated function tools, and merges `extraBody.include` without duplicates:

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

</details>

<details>
<summary><b>Azure OpenAI</b></summary>

The `azure_openai` provider talks to your Azure OpenAI resource via the OpenAI **Responses API** (`/openai/v1/responses`). Model names map to **deployment names**, not OpenAI model IDs. Two authentication modes are supported.

**Mode 1: Static API key** (simplest)

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

**Mode 2: Microsoft Entra ID (Azure AD) via `DefaultAzureCredential`**

Omit `apiKey` (or leave it empty / unset). The provider falls back to [`DefaultAzureCredential`](https://learn.microsoft.com/azure/developer/python/sdk/authentication/credential-chains#defaultazurecredential-overview) and acquires a bearer token scoped to `https://cognitiveservices.azure.com/.default` for every request. The Azure SDK's own MSAL-backed cache returns valid tokens without a network round-trip.

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

Install the optional dependency:

```bash
python -m pip install 'nanobot-ai[azure]'
```

`DefaultAzureCredential` walks this chain in order and uses the first identity that succeeds:

1. **EnvironmentCredential** — reads `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and one of `AZURE_CLIENT_SECRET` / `AZURE_CLIENT_CERTIFICATE_PATH` / `AZURE_USERNAME` + `AZURE_PASSWORD`.
2. **WorkloadIdentityCredential** — for AKS workload-identity / federated tokens (`AZURE_FEDERATED_TOKEN_FILE`).
3. **ManagedIdentityCredential** — for Azure VMs, App Service, Functions, Container Apps, etc.
4. **AzureCliCredential** — uses the token from `az login` on your dev machine.
5. **AzurePowerShellCredential** — uses the token from `Connect-AzAccount`.
6. **AzureDeveloperCliCredential** — uses the token from `azd auth login`.
7. **InteractiveBrowserCredential** *(disabled by default)*.

The identity that ends up signing the request **must be assigned the `Cognitive Services OpenAI User` RBAC role** (or higher) on the Azure OpenAI resource. Without that role you will see `401`/`403` errors at the first request.

> `apiBase` remains mandatory in both modes — it's your Azure resource endpoint and cannot be inferred. If neither `apiKey` is set nor `azure-identity` is installed, the provider raises a clear error pointing you at `python -m pip install 'nanobot-ai[azure]'`.

</details>

<details>
<summary><b>Skywork / APIFree</b></summary>

Skywork uses APIFree's OpenAI-compatible Agent API endpoint. Configure the provider once, then use Skywork model IDs such as `skywork-ai/skyclaw-v1`.

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

You can also reference `${APIFREE_API_KEY}` in `apiKey` if that is how your environment names the credential.

</details>

<details>
<summary><b>AWS Bedrock (Converse API)</b></summary>

Bedrock uses the native `bedrock-runtime` Converse API, so it can call Bedrock model IDs such as Claude Opus 4.7, Claude Sonnet, Amazon Nova, Meta Llama, Mistral, Qwen, and other models that support Converse. It supports normal chat, streaming, tool calling, tool results, token usage, and Bedrock error metadata.

This provider is for Bedrock's native Converse API, not Bedrock's OpenAI-compatible `/openai/v1` endpoint. For OpenAI-compatible Bedrock models, you can still use `custom` if you specifically want that API surface.

**1. Configure credentials**

Use the normal AWS credential chain (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, an AWS profile, or an IAM role). The IAM identity needs:

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

You can also set `providers.bedrock.apiKey` to a Bedrock API key; nanobot exports it as `AWS_BEARER_TOKEN_BEDROCK` for the AWS SDK.

Credential options:

- **AWS CLI/default profile**: leave `apiKey` and `profile` empty, then run `aws configure` or provide `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
- **Named AWS profile**: set `profile` to a profile from `~/.aws/config` or `~/.aws/credentials`.
- **IAM role**: on EC2/ECS/Lambda, leave `apiKey` and `profile` empty and attach a role with Bedrock permissions.
- **Bedrock API key**: set `apiKey` or `AWS_BEARER_TOKEN_BEDROCK`; `profile` can stay `null`.

**2. Minimal config**

For a non-Anthropic model such as Amazon Nova:

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

With a Bedrock API key:

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

With a named AWS profile:

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

**3. Claude Opus 4.7 example**

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

For regional routing, use one of Bedrock's inference IDs, for example `bedrock/us.anthropic.claude-opus-4-7`, `bedrock/eu.anthropic.claude-opus-4-7`, or `bedrock/jp.anthropic.claude-opus-4-7`.

Claude Opus 4.7 does not accept `temperature`, `top_p`, or `top_k`; nanobot omits `temperature` automatically for this model. If `reasoningEffort` is set to `low`, `medium`, `high`, `max`, or `adaptive`, nanobot sends Bedrock's adaptive thinking parameter.

Anthropic models on Bedrock can also require Anthropic use-case registration and are subject to Anthropic-supported country/region restrictions. If Claude fails with a `ValidationException` about unsupported countries or regions, try a non-Anthropic Bedrock model such as Amazon Nova to verify the provider setup.

**4. Model IDs**

Use Bedrock model IDs or inference profile IDs with a `bedrock/` prefix in nanobot config. nanobot removes the prefix before calling AWS.

Examples:

- `bedrock/amazon.nova-micro-v1:0`
- `bedrock/amazon.nova-lite-v1:0`
- `bedrock/global.anthropic.claude-opus-4-7`
- `bedrock/us.anthropic.claude-opus-4-7`
- `bedrock/openai.gpt-oss-20b-1:0`
- `bedrock/meta.llama...`
- `bedrock/mistral...`

Check the Bedrock console for the exact model ID and region availability. Some models require cross-region inference profile IDs such as `us.*`, `eu.*`, or `global.*`.

**5. Advanced model fields**

Model-specific fields can be supplied with `extraBody`; nanobot merges it into Converse `additionalModelRequestFields`:

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

Use `apiBase` only for a custom Bedrock Runtime endpoint URL, such as a VPC endpoint or proxy. It is not needed for normal AWS regions.

Current scope: nanobot passes `messages`, `system`, `inferenceConfig`, `toolConfig`, and `additionalModelRequestFields`. Bedrock Prompt Management, Guardrails, `serviceTier`, and other top-level Converse options are not first-class config fields yet.

**6. Quick checks**

```bash
# For AWS credential-chain usage:
aws sts get-caller-identity

# For API-key usage:
export AWS_BEARER_TOKEN_BEDROCK="your-bedrock-api-key"
export AWS_REGION="us-east-1"
```

Then run:

```bash
nanobot agent -m "Reply with one short sentence."
```

</details>


<details>
<summary><b>OpenAI Codex (OAuth)</b></summary>

Codex uses OAuth instead of API keys. Requires a ChatGPT Plus or Pro account. `nanobot provider login` stores the OAuth session outside config. A `providers.openai_codex` block is optional and is only needed for provider-specific settings such as a proxy.

**1. Login:**
```bash
nanobot provider login openai-codex
```

If the machine running nanobot cannot open a graphical browser, copy the printed URL into a real browser. For remote SSH login, open the URL locally, then paste the final `http://localhost:1455/auth/callback?...` redirect URL back into the terminal when prompted.

**2. Optional proxy** (merge into `~/.nanobot/config.json` if Codex OAuth or Codex API traffic must use a proxy):

```json
{
  "providers": {
    "openai_codex": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

The proxy applies to Codex OAuth token refresh, interactive token exchange, and Codex Responses API requests. It does not affect other providers; configure `proxy` separately on each supported provider that needs it.

**3. Set model** (merge into `~/.nanobot/config.json`):
```json
{
  "modelPresets": {
    "codex": {
      "provider": "openai_codex",
      "model": "gpt-5.1-codex",
      "reasoningEffort": "high"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "codex"
    }
  }
}
```

Use `reasoningEffort` in the preset to send a Codex reasoning effort such as `"low"`, `"medium"`, `"high"`, or another value supported by the selected model. When `provider` is explicitly `openai_codex`, the model name does not need the `openai-codex/` prefix.

**4. Chat:**
```bash
nanobot agent -m "Hello!"

# Target a specific workspace/config locally
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test -m "Hello!"
```

> Docker users: use `docker run -it` for interactive OAuth login.

</details>


<details>
<summary><b>GitHub Copilot (OAuth)</b></summary>

GitHub Copilot uses OAuth instead of API keys. Requires a [GitHub account with a plan](https://github.com/features/copilot/plans) configured. No `providers.github_copilot` block is needed in `config.json`; `nanobot provider login` stores the OAuth session outside config.

For GitHub Enterprise / Copilot for Business, set the endpoint overrides you need before login:
```bash
export NANOBOT_GITHUB_COPILOT_CLIENT_ID="your-enterprise-client-id"
export NANOBOT_GITHUB_DEVICE_CODE_URL="https://ghe.example/login/device/code"
export NANOBOT_GITHUB_ACCESS_TOKEN_URL="https://ghe.example/login/oauth/access_token"
export NANOBOT_GITHUB_USER_URL="https://api.ghe.example/user"
export NANOBOT_COPILOT_TOKEN_URL="https://api.ghe.example/copilot_internal/v2/token"
export NANOBOT_COPILOT_BASE_URL="https://copilot-api.ghe.example"
```

**1. Login:**
```bash
nanobot provider login github-copilot
```

**2. Set model** (merge into `~/.nanobot/config.json`):
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

**3. Chat:**
```bash
nanobot agent -m "Hello!"

# Target a specific workspace/config locally
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test -m "Hello!"
```

> Docker users: use `docker run -it` for interactive OAuth login.

</details>

<details>
<summary><b>OpenCode Zen / Go</b></summary>

OpenCode Zen and OpenCode Go are available through nanobot's built-in
OpenAI-compatible provider flow. They share the `OPENCODE_API_KEY` environment
variable, but use separate provider keys and default base URLs:

| Provider | Default API base | Model prefix accepted by nanobot |
|----------|------------------|-----------------------------------|
| `opencode_zen` | `https://opencode.ai/zen/v1` | `opencode/<model-id>` |
| `opencode_go` | `https://opencode.ai/zen/go/v1` | `opencode-go/<model-id>` |

OpenCode Zen:

```json
{
  "providers": {
    "opencodeZen": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "opencodeZen": {
      "provider": "opencode_zen",
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

OpenCode Go:

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

OpenCode's own docs list models across `responses`, `messages`,
provider-specific model endpoints, and `chat/completions`. nanobot's OpenCode
providers use the OpenAI-compatible `chat/completions` path, so pick model IDs
from that endpoint family. The `opencode/...` and `opencode-go/...` prefixes are
accepted for config readability and stripped before sending the request.

</details>

<details>
<summary><b>LongCat (OpenAI-compatible)</b></summary>

LongCat is available through nanobot's built-in OpenAI-compatible provider flow. The default API base already points to `https://api.longcat.chat/openai/v1`, so you usually only need to set `apiKey`.

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

Current LongCat API docs list `LongCat-2.0-Preview` as the supported model. The older `LongCat-Flash-*` models were retired by LongCat on 2026-05-29.

</details>

<details>
<summary><b>Xiaomi MiMo</b></summary>

Xiaomi MiMo models are automatically detected by the `xiaomi_mimo` provider when the model name contains `mimo`. The default API base is `https://api.xiaomimimo.com/v1`.

> **Token Plan**: If you're using MiMo's token plan, override `apiBase` with the dedicated endpoint:
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
> Use the model ID and API key from the MiMo token plan console, and check the MiMo platform for the latest supported model names.

</details>

<details>
<summary><b>StepFun Step Plan (subscription)</b></summary>

Step Plan is StepFun's subscription-based service for high-frequency AI developers. If you're on a Step Plan subscription, override `apiBase` in the existing `stepfun` provider config to point to the dedicated Step Plan endpoint.

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

Supported models include `step-3.5-flash`, `step-3.5-flash-2603`, and `step-router-v1`.

</details>

<details>
<summary><b>Ant Ling (OpenAI-compatible)</b></summary>

Ant Ling is available through nanobot's built-in OpenAI-compatible provider flow. The default API base points to `https://api.ant-ling.com/v1`, so you usually only need to set `apiKey`.

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

Official OpenAI-compatible model names include `Ling-2.6-1T`, `Ling-2.6-flash`, `Ling-2.5-1T`, `Ling-1T`, `Ring-2.5-1T`, and `Ring-1T`.

</details>

<details>
<summary><b>Custom Provider (Any OpenAI-compatible API)</b></summary>

Connects directly to any OpenAI-compatible endpoint — llama.cpp, Together AI, Fireworks, Azure OpenAI, or any self-hosted server. Model name is passed as-is.

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

> For local servers that don't require authentication, set `apiKey` to `null`.
>
> `custom` is the right choice for providers that expose an OpenAI-compatible **chat completions** API. It does **not** force third-party endpoints onto the OpenAI/Azure **Responses API**.
>
> If your proxy or gateway is specifically Responses-API-compatible, configure the `azure_openai` provider shape and point `apiBase` at that endpoint:
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
> Anthropic-compatible endpoints are separate: use `providers.anthropic.apiBase` and set the preset provider to `anthropic`. Arbitrary custom provider names do not use the Anthropic Messages API format.
>
> In short: **chat-completions-compatible endpoint → `custom` or a named custom provider**; **Responses-compatible endpoint → `azure_openai`**; **Anthropic-compatible endpoint → `anthropic` with `apiBase`**.

Some OpenAI-compatible gateways expose request-body extensions such as vLLM guided decoding or local sampling controls. Put those under `extraBody`; nanobot merges them into the chat-completions request body after its provider defaults:

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

If a custom OpenAI-compatible endpoint exposes a provider-specific thinking toggle, set `thinkingStyle` so nanobot can translate `reasoningEffort` into the right request body. Supported styles are `thinking_type` (`{"thinking":{"type":"enabled"}}`), `enable_thinking` (`{"enable_thinking": true}`), and `reasoning_split` (`{"reasoning_split": true}`):

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

Leave `thinkingStyle` unset unless the endpoint explicitly documents one of those wire formats. `extraBody` is still applied last, so advanced users can override the generated value.

</details>

<a id="local-providers"></a>
<a id="ollama-local"></a>
<details>
<summary><b>Ollama (local)</b></summary>

Run a local model with Ollama, then add to config:

**1. Start Ollama** (example):
```bash
ollama run llama3.2
```

**2. Add to config** (partial — merge into `~/.nanobot/config.json`):
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

> `provider: "auto"` also works when `providers.ollama.apiBase` is configured, but pinning `"provider": "ollama"` inside the preset is the clearest option.

</details>

<details>
<summary><b>LM Studio (local)</b></summary>

[LM Studio](https://lmstudio.ai/) provides a local OpenAI-compatible server for running LLMs. Download models through the LM Studio UI, then start the local server.

**1. Start LM Studio server:**
- Launch LM Studio
- Go to the "Local Server" tab
- Load a model (e.g., Llama, Mistral, Qwen)
- Click "Start Server" (default port: 1234)

**2. Add to config** (partial — merge into `~/.nanobot/config.json`):
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

> **Note:** Set `apiKey` to `null` for LM Studio since it runs locally and doesn't require authentication. The model name should match what's shown in the LM Studio UI. `provider: "auto"` also works when `providers.lm_studio.apiBase` is configured, but pinning `"provider": "lm_studio"` inside the preset is the clearest option.

</details>

<a id="atomic-chat-local"></a>
<details>
<summary><b>Atomic Chat (local)</b></summary>

[Atomic Chat](https://atomic.chat/) is a local-first desktop app that exposes an **OpenAI-compatible** HTTP API (default `http://localhost:1337/v1`). This setup applies when you want to run nanobot against a model on your own machine instead of a hosted API provider.

**1. Start Atomic Chat**

- Install [Atomic Chat](https://atomic.chat/) on your machine.
- Open Atomic Chat, download a model, and keep the app running. The local API is enabled by default.
- Copy the model ID exposed by the local API. For example, the model ID for `Qwen 3 32B` might be `qwen3-32b`.

**2. Add to config** (partial — merge into `~/.nanobot/config.json`):

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

> **Note:** Replace `qwen3-32b` with the model ID from Atomic Chat. Set `apiKey` to `null` if your Atomic Chat server does not require a key. If it does, set `apiKey` (or the `ATOMIC_CHAT_API_KEY` environment variable) to the value Atomic Chat expects.

> `provider: "auto"` also works when `providers.atomic_chat.apiBase` is configured, but pinning `"provider": "atomic_chat"` inside the preset is the clearest option.

</details>

<details>
<summary><b>OpenVINO Model Server (local / OpenAI-compatible)</b></summary>

Run LLMs locally on Intel GPUs using [OpenVINO Model Server](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html). OVMS exposes an OpenAI-compatible API at `/v3`.

> Requires Docker and an Intel GPU with driver access (`/dev/dri`).

**1. Pull the model** (example):

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

> This downloads the model weights. Wait for the container to finish before proceeding.

**2. Start the server** (example):

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

**3. Add to config** (partial — merge into `~/.nanobot/config.json`):

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

> OVMS is a local server — no API key required. Supports tool calling (`--tool_parser gptoss`), reasoning (`--reasoning_parser gptoss`), and streaming. See the [official OVMS docs](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) for more details.
</details>

<a id="vllm-local-openai-compatible"></a>
<details>
<summary><b>vLLM (local / OpenAI-compatible)</b></summary>

Run your own model with vLLM or any OpenAI-compatible server, then add to config:

**1. Start the server** (example):
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. Add to config** (partial — merge into `~/.nanobot/config.json`):

*Provider (set API key to null for local servers):*
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

*Model preset:*
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

Contributor notes for adding new providers live in [`development.md`](./development.md#adding-an-llm-provider).

## Model Presets

Model presets let you name a complete model configuration and switch it at runtime with `/model <preset>`. They are the recommended way to configure models because the same names can be reused for startup selection, chat-command switching, and fallback chains.

Existing configs do not need to change. Direct `agents.defaults.model`, `provider`, `maxTokens`, `contextWindowTokens`, `temperature`, and `reasoningEffort` fields still define the implicit `default` preset. For new configs, prefer top-level `modelPresets` plus `agents.defaults.modelPreset`.

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

`modelPresets` is a top-level object. The keys under it (`fast`, `deep`, `coding`, etc.) are user-defined preset names. Each preset supports:

| Field | Description |
|-------|-------------|
| `label` | Optional display name shown in model lists. |
| `model` | Model name to use for this preset. |
| `provider` | Provider name, or `"auto"` to use provider auto-detection. |
| `maxTokens` | Maximum completion/output tokens. |
| `contextWindowTokens` | Context window size used by prompt building and consolidation decisions. |
| `temperature` | Sampling temperature. |
| `reasoningEffort` | Optional reasoning/thinking setting. Provider support varies. |

`default` is reserved and always means the implicit preset built from direct `agents.defaults.*` fields; do not define `modelPresets.default`. Use `/model default` to switch back to those direct fields in an existing config.

Set `agents.defaults.modelPreset` to choose the startup preset. When `modelPreset` is `null` or omitted, startup uses the implicit `default` preset from direct `agents.defaults.*` fields. Runtime changes made with `/model <preset>` are not written back to `config.json`; they affect future turns until the process restarts or another model/config change replaces them.

### Model Fallbacks

`agents.defaults.fallbackModels` defines an ordered failover chain for the active model configuration. The primary model is still selected by `agents.defaults.modelPreset` or, in older configs, by the implicit `default` preset from direct `agents.defaults.*` fields.

Each fallback candidate can be either:

- A preset name from `modelPresets`, such as `"deep"`. This is the recommended form. The preset's full model, provider, generation, and context-window config is used.
- An inline fallback object with at least `provider` and `model`. Optional `maxTokens`, `contextWindowTokens`, and `temperature` fields inherit from the active primary config when omitted. `reasoningEffort` does not inherit; omit it to leave reasoning off for that fallback, or set it explicitly for models that support reasoning.

Preset fallback chain:

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

String entries are preset names, not raw model names. In the example above, `"deep"` means `modelPresets.deep`; nanobot will not interpret it as a provider model ID. Changing a preset updates both `/model <preset>` switching and any fallback chain that references it.

Inline fallback object:

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

Use inline objects only when a fallback is not worth naming as a reusable preset. `fallbackModels` belongs under `agents.defaults`, not inside individual `modelPresets` entries.

Failover normally runs when the primary provider returns a retryable model/provider error before any answer text has been streamed. Stream-stall timeouts are the recovery exception: if the provider already emitted partial answer text and then stalls, nanobot closes the current stream segment and retries/fails over in a new segment. Typical fallback cases include timeouts, connection errors, 5xx server errors, 429 rate limits, overloads, and quota/balance exhaustion. It does not run for malformed requests, authentication/permission errors, content filtering/refusals, or context-length/message-format errors.

If fallback candidates use smaller `contextWindowTokens` values, nanobot builds context using the smallest window in the active chain so every candidate can receive the same prompt.

## Transcription Settings

Audio transcription is a shared capability used by chat-channel voice messages and by WebUI microphone input. Chat-channel voice messages are transcribed automatically before they enter the agent. WebUI microphone input is transcribed into the composer first, so you can edit the text before sending.

Configure transcription under the top-level `transcription` section:

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

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Enables audio transcription for both chat-channel voice messages and WebUI microphone input. |
| `provider` | `"groq"` | Transcription backend: `"groq"`, `"openai"`, `"openrouter"`, `"xiaomi_mimo"`, `"stepfun"`, or `"assemblyai"`. |
| `model` | provider default | Optional transcription model override. Defaults to `whisper-large-v3` for Groq, `whisper-1` for OpenAI, `openai/whisper-1` for OpenRouter, `mimo-v2.5-asr` for Xiaomi MiMo ASR, `stepaudio-2.5-asr` for StepFun ASR, and `universal-3-pro,universal-2` for AssemblyAI. OpenRouter accepts only speech-to-text models on its transcription endpoint, such as `nvidia/parakeet-tdt-0.6b-v3`, `openai/whisper-1`, or `openai/gpt-4o-transcribe`; chat LLMs are rejected there. AssemblyAI accepts a comma-separated model fallback list. |
| `language` | `null` | Optional ISO-639 language hint, e.g. `"en"`, `"zh"`, `"ko"`, or `"ja"`. |
| `maxDurationSec` | `120` | Maximum WebUI recording duration. |
| `maxUploadMb` | `25` | Maximum WebUI audio upload size. |

Provider and language resolution is intentionally ordered for backwards compatibility:

1. `transcription.provider` / `transcription.language`
2. Legacy `channels.transcriptionProvider` / `channels.transcriptionLanguage`
3. Built-in defaults (`provider: "groq"`, no language hint)

The legacy `channels.*` transcription fields existed before transcription became a shared capability across chat channels and WebUI microphone input. They are still read so older `config.json` files keep working, but they are no longer the preferred configuration surface. If both old and new fields are present, the top-level `transcription` values are the source of truth.

Transcription credentials are intentionally not stored in `transcription`. Put the API key and optional endpoint in the matching provider config:

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

Selecting a transcription provider does not configure credentials by itself. For example, the effective provider may default to Groq for compatibility, but transcription is only usable when `providers.groq.apiKey` or the matching environment-backed config is available. The Settings UI writes only the top-level `transcription` fields.

If you are adding a new transcription provider, see [`development.md`](./development.md#adding-a-transcription-provider).

## Channel Settings

Global settings that apply to all channels. Configure under the `channels` section in `~/.nanobot/config.json`:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "extractDocumentText": true,
    "sendMaxRetries": 3,
    "telegram": {
      "enabled": false
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `sendProgress` | `true` | Stream agent's text progress to the channel |
| `sendToolHints` | `false` | Stream tool-call hints (e.g. `read_file("…")`) |
| `showReasoning` | `true` | Allow channels to surface model reasoning/thinking content (DeepSeek-R1 `reasoning_content`, Anthropic `thinking_blocks`, inline `<think>` tags). Reasoning flows as a dedicated stream with `_reasoning_delta` / `_reasoning_end` markers — channels override `send_reasoning_delta` / `send_reasoning_end` to render in-place updates. Even with `true`, channels without those overrides stay no-op silently. Currently surfaced on CLI and WebSocket/WebUI (italic shimmer header, auto-collapses after the stream ends); Telegram / Slack / Discord / Feishu / WeChat / Matrix keep the base no-op until their bubble UI is adapted. Independent of `sendProgress`. |
| `extractDocumentText` | `true` | Extract supported document/text attachments into the model prompt. Set to `false` to keep document content out of the prompt and include attachment path references instead. |
| `sendMaxRetries` | `3` | Max delivery attempts per outbound message, including the initial send (0-10 configured, minimum 1 actual attempt) |

`channels.transcriptionProvider` and `channels.transcriptionLanguage` are deprecated compatibility fields. They remain as a read-only fallback for older configs, but new configuration should use top-level `transcription.provider` and `transcription.language`.

`sendProgress` and `sendToolHints` can also be overridden per channel. The global values stay as defaults for channels that do not set their own value:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "sendProgress": false
    },
    "websocket": {
      "enabled": true,
      "sendToolHints": true
    }
  }
}
```

Telegram `richMessages` defaults to `false`. Enable it only to opt in to Bot API 10.1 `sendRichMessage` rendering; leave it disabled for Telegram Web clients that show unsupported-message errors for rich messages.

### Retry Behavior

Retry is intentionally simple.

When a channel `send()` raises, nanobot retries at the channel-manager layer. By default, `channels.sendMaxRetries` is `3`, and that count includes the initial send.

- **Attempt 1**: Send immediately
- **Attempt 2**: Retry after `1s`
- **Attempt 3**: Retry after `2s`
- **Higher retry budgets**: Backoff continues as `1s`, `2s`, `4s`, then stays capped at `4s`
- **Transient failures**: Network hiccups and temporary API limits often recover on the next attempt
- **Permanent failures**: Invalid tokens, revoked access, or banned channels will exhaust the retry budget and fail cleanly

> [!NOTE]
> This design is deliberate: channel implementations should raise on delivery failure, and the channel manager owns the shared retry policy.
>
> Some channels may still apply small API-specific retries internally. For example, Telegram separately retries timeout and flood-control errors before surfacing a final failure to the manager.
>
> If a channel is completely unreachable, nanobot cannot notify the user through that same channel. Watch logs for `Failed to send to {channel} after N attempts` to spot persistent delivery failures.

## Web Tools

nanobot incorporates basic tools for accessing the web. These include searching via APIs, and fetching arbitrary web pages in Markdown format. They are enabled by default, and can be configured in `~/.nanobot/config.json` under `tools.web`.

If you want to disable them, which removes both `web_search` and `web_fetch` from the tool list sent to the LLM, set `tools.web.enable` to `false`:

```json
{
  "tools": {
    "web": {
      "enable": false
    }
  }
}
```

nanobot uses a shared SSRF guard for built-in web fetches and HTTP/SSE MCP connections. By default it blocks loopback, RFC1918/private ranges, CGNAT/Tailscale ranges, link-local addresses, and cloud metadata endpoints. If you need to allow trusted private ranges, explicitly exempt them from SSRF blocking with `tools.ssrfWhitelist`:

```json
{
  "tools": {
    "ssrfWhitelist": ["100.64.0.0/10"]
  }
}
```

Keep whitelist entries as narrow as possible, such as a single host CIDR (`192.168.1.50/32`). The whitelist is global for the shared SSRF guard; it is not limited to one tool or one MCP server.

> [!TIP]
> Use `proxy` in `tools.web` to route all web requests (search + fetch) through a proxy:
> ```json
> { "tools": { "web": { "proxy": "http://127.0.0.1:7890" } } }
> ```

### `tools.web`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | boolean | `true` | Enable or disable all built-in web tools (`web_search` + `web_fetch`) |
| `proxy` | string or null | `null` | Proxy for all web requests, for example `http://127.0.0.1:7890` |
| `userAgent` | string or null | `null` | User-Agent header for all web requests. If null, a browser one will be used |

### Web Search

nanobot supports multiple web search providers. Configure in `~/.nanobot/config.json` under `tools.web.search`.

By default, web search uses `duckduckgo`, and it works out of the box without an API key.

| Provider | Config fields | Env var fallback | Free |
|----------|--------------|------------------|------|
| `brave` | `apiKey` | `BRAVE_API_KEY` | No |
| `tavily` | `apiKey` | `TAVILY_API_KEY` | No |
| `jina` | `apiKey` | `JINA_API_KEY` | Free tier (10M tokens) |
| `kagi` | `apiKey` | `KAGI_API_KEY` | No |
| `olostep` | `apiKey` | `OLOSTEP_API_KEY` | No |
| `bocha` | `apiKey` | `BOCHA_API_KEY` | Free tier (1M calls for startups) |
| `volcengine` | `apiKey` | `VOLCENGINE_SEARCH_API_KEY` or `WEB_SEARCH_API_KEY` | Monthly quota, then paid |
| `keenable` | `apiKey` (optional) | `KEENABLE_API_KEY` | Yes (no key needed; key raises limits) |
| `searxng` | `baseUrl` | `SEARXNG_BASE_URL` | Yes (self-hosted) |
| `duckduckgo` (default) | — | — | Yes |

**Brave:**
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

**Tavily:**
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

**Jina** (free tier with 10M tokens):
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

**Kagi:**
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

**Olostep:**
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

You can also set `OLOSTEP_API_KEY` in the environment instead of storing it in config.

**Bocha** (AI-optimized search, free tier available):
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

Create your API key at [open.bochaai.com](https://open.bochaai.com).
Bocha returns structured results optimized for AI consumption, with optional summaries.
You can set `BOCHA_API_KEY` in the environment instead of storing it in config.

**Volcengine Search:**
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

You can also set `WEB_SEARCH_API_KEY` for compatibility with the Volcengine web-search skill. Create the key in the [Volcengine web search console](https://console.volcengine.com/search-infinity/web-search), then copy it from [API keys](https://console.volcengine.com/search-infinity/api-key). Volcengine Ark keys are separate and do not work for this search provider.

**Keenable** (works without an API key on the free tier):
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

Keenable search works out of the box with no account, via its token-less public endpoint (free tier, limited to 1,000 requests/hour). Set `apiKey` (or `KEENABLE_API_KEY`) from [keenable.ai](https://keenable.ai) to remove the hourly limit.

**SearXNG** (self-hosted, no API key needed):
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

**DuckDuckGo** (zero config):
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

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `provider` | string | `"duckduckgo"` | Search backend: `brave`, `tavily`, `jina`, `kagi`, `olostep`, `bocha`, `volcengine`, `keenable`, `searxng`, `duckduckgo` |
| `apiKey` | string | `""` | API key for API-backed search providers |
| `baseUrl` | string | `""` | Base URL for SearXNG |
| `maxResults` | integer | `5` | Results per search (1–10) |

### Web Fetch

> [!TIP]
> If you are having issues with JS proof-of-work or Cloudflare captchas, set a random user agent and disable Jina Reader:
> ```json
> { "tools": { "web": { "userAgent": "Not-A-Browser", "fetch": { "useJinaReader": false } } } }
> ```

nanobot by default uses [Jina Reader](https://jina.ai/reader/), a third-party API, to convert arbitrary pages into Markdown format for easy digestion by the LLM, with a local fallback based on [readability-lxml](https://github.com/buriy/python-readability) if the former fails.

If you want to always use the local conversion, you can force it using:

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

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `useJinaReader` | boolean | `true` | If true, Jina Reader will be preferred over the local conversion |

## Image Generation

Image generation is configured under `tools.imageGeneration` and uses credentials from the selected provider's `providers.<name>` block.

See [Image Generation](./image-generation.md) for WebUI usage, provider examples, artifact storage, and troubleshooting.

## MCP (Model Context Protocol)

> [!TIP]
> The config format is compatible with Claude Desktop / Cursor. You can copy MCP server configs directly from any MCP server's README.

nanobot supports [MCP](https://modelcontextprotocol.io/) — connect external tool servers and use them as native agent tools.

Add MCP servers to your `config.json`:

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

Two transport modes are supported:

| Mode | Config | Example |
|------|--------|---------|
| **Stdio** | `command` + `args` | Local process via `npx` / `uvx` |
| **HTTP** | `url` + `headers` (optional) | Remote endpoint (`https://mcp.example.com/sse`) |

> [!IMPORTANT]
> HTTP/SSE MCP URLs are validated before probing or connecting, and every outgoing MCP HTTP request is validated again before redirects are followed. `localhost`, `127.0.0.1`, RFC1918/private IPs, CGNAT/Tailscale ranges, link-local addresses, and cloud metadata endpoints are blocked by default. This can break previously working local or private HTTP MCP configs until the endpoint is explicitly allowed with `tools.ssrfWhitelist`, preferably with a single-host CIDR such as `127.0.0.1/32`, `::1/128`, or `192.168.1.50/32`. Stdio MCP servers are not affected.

Use `toolTimeout` to override the default 30s per-call timeout for slow servers:

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

Use `enabledTools` to register only a subset of tools from an MCP server:

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

`enabledTools` accepts either the raw MCP tool name (for example `read_file`) or the wrapped nanobot tool name (for example `mcp_filesystem_write_file`).

- Omit `enabledTools`, or set it to `["*"]`, to register all capabilities (tools, resources, and prompts).
- Set `enabledTools` to `[]` to register no tools from that server. Resources and prompts are also skipped, since they have no per-name filter.
- Set `enabledTools` to a non-empty list of names to register only those tools — resources and prompts are not registered.

MCP tools are automatically discovered and registered on startup. The LLM can use them alongside built-in tools — no extra configuration needed.




## Security

> [!TIP]
> For production deployments, set both `"restrictToWorkspace": true` and `"tools.exec.sandbox": "bwrap"` in your config. `restrictToWorkspace` enables nanobot's application-level workspace guards; `tools.exec.sandbox` provides process-level isolation for shell commands.

For API keys, tokens, and other secrets, see [Environment Variables for Secrets](#environment-variables-for-secrets) — avoid storing them directly in `config.json`.

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | When `true`, enables nanobot's application-level workspace guards for workspace-aware tools. File tools resolve paths under the active workspace; selected internal roots can be added as read-only or explicitly write-enabled roots, and media uploads are read-only by default. Shell execution rejects workspace-external `working_dir` values and applies best-effort command path checks, but this is not an OS sandbox. |
| `tools.exec.sandbox` | `""` | Sandbox backend for shell commands. Set to `"bwrap"` to wrap exec calls in a [bubblewrap](https://github.com/containers/bubblewrap) sandbox — the process can only see the workspace (read-write) and media directory (read-only); config files and API keys are hidden. Automatically enables workspace restriction for file tools. **Linux only** — requires `bwrap` installed (`apt install bubblewrap`; pre-installed in the Docker image). Not available on macOS or Windows (bwrap depends on Linux kernel namespaces). |
| `tools.exec.enable` | `true` | When `false`, the shell `exec` tool is not registered at all. Use this to completely disable shell command execution. |
| `tools.exec.timeout` | `60` | Default hard timeout in seconds for shell commands. Config values may exceed the per-call tool cap; set `0` to disable the hard timeout for trusted long-running commands. |
| `tools.exec.pathPrepend` | `""` | Extra directories to prepend to `PATH` when running shell commands. Use this when configured tools should win executable lookup precedence, such as a Python virtual environment's `bin` or `Scripts` directory. |
| `tools.exec.pathAppend` | `""` | Extra directories to append to `PATH` when running shell commands (e.g. `/usr/sbin` for `ufw`). |
| `tools.ssrfWhitelist` | `[]` | CIDR ranges exempted from the shared SSRF guard used by web fetches and HTTP/SSE MCP connections. Prefer exact host CIDRs such as `192.168.1.50/32`; broad ranges increase SSRF exposure. |
| `channels.*.allowFrom` | omitted | Access control per channel. Omit to use pairing-only mode; set `["*"]` to allow everyone; or list specific user IDs. See [Pairing](#pairing) for details. |

**Docker security**: The official Docker image runs as a non-root user (`nanobot`, UID 1000) with bubblewrap pre-installed. When using `docker-compose.yml`, the container drops all Linux capabilities except `SYS_ADMIN` (required for bwrap's namespace isolation).


## Pairing

Pairing lets users get access to the bot through a simple code exchange — no config editing required. This works for both new users and existing users connecting from a new channel (e.g. someone already approved on Telegram now setting up Discord).

### How it works

1. A user sends a DM to the bot on any channel (Telegram, Discord, Slack, etc.) where they aren't yet approved.
2. The bot replies with a pairing code (like `ABCD-EFGH`) and tells them to forward it to you.
3. You approve the code:

```text
/pairing approve ABCD-EFGH
```

4. The user can now chat with the bot normally.

Pairing only works in **DMs** — unapproved users in group chats are silently ignored.

### Pairing-only mode

By default, if you don't set `allowFrom`, anyone who isn't approved yet will get a pairing code when they DM the bot. This means you can skip `allowFrom` entirely and manage all access through pairing:

```json
{
  "channels": {
    "telegram": {
      "enabled": true
    }
  }
}
```

If you prefer to allow everyone without approval:

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

### Managing access

| Command | What it does |
|---------|-------------|
| `/pairing` | Show all pending pairing requests |
| `/pairing approve <code>` | Approve a request — the sender can now chat |
| `/pairing deny <code>` | Reject a pending request |
| `/pairing revoke <user_id>` | Remove a previously approved user from the current channel |
| `/pairing revoke <channel> <user_id>` | Remove a user from a specific channel |

You can find user IDs in the output of `/pairing list`.

From the terminal:

```bash
nanobot agent -m "/pairing list"
nanobot agent -m "/pairing approve ABCD-EFGH"
```


## Gateway Heartbeat

The gateway can run a protected heartbeat cron job that periodically checks `HEARTBEAT.md` in the active workspace. This is enabled by default when you run `nanobot gateway`.

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

If `HEARTBEAT.md` has tasks under `## Active Tasks`, the agent executes them and sends only useful/actionable results to the most recently active chat target. If the file has no active tasks, or the result is routine with nothing useful to report, the heartbeat is skipped silently.

This is intentionally different from user-created cron jobs. A cron job created with the `cron` tool runs as a scheduled turn in its origin chat/session and normally delivers the result back to that channel. Use `HEARTBEAT.md` for recurring background checks that should not notify the user on every run.

The heartbeat job is backed by the same cron service as user-created reminders. It is stored under the active workspace (`<workspace>/cron/jobs.json`) and shows up in `cron(action="list")` as `heartbeat`, but it is system-managed and cannot be removed with the `cron` tool. Disable it through config and restart the gateway if you do not want periodic heartbeat checks.

| Option | Default | Description |
|--------|---------|-------------|
| `gateway.heartbeat.enabled` | `true` | Register the built-in heartbeat cron job on gateway startup. |
| `gateway.heartbeat.intervalS` | `1800` | Seconds between heartbeat checks. |
| `gateway.heartbeat.keepRecentMessages` | `8` | Number of recent heartbeat-session messages to retain after each run. |
| `gateway.restartMode` | `auto` | Restart strategy for `/restart`: `auto` uses `spawn` on Windows foreground runs and `exec` elsewhere. Use `exit` with Windows service wrappers such as WinSW or nssm so the service manager owns the restart. |


## Subagent Concurrency

By default, nanobot only allows one spawned subagent at a time. When the limit is reached, the `spawn` tool returns an error so the agent can decide to wait or rearrange its work. This protects local LLM servers from loading multiple KV caches at once. If your provider can handle more parallel work, raise the limit:

```json
{
  "agents": {
    "defaults": {
      "maxConcurrentSubagents": 2
    }
  }
}
```

Subagents also stop immediately when one of their tools returns an execution error. That default keeps failures visible to the parent agent. If your subagent workflows use tools that can fail transiently and should be retried or worked around by the model, disable hard-stop behavior:

```json
{
  "agents": {
    "defaults": {
      "failOnToolError": false
    }
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `agents.defaults.maxConcurrentSubagents` | `1` | Maximum number of spawned subagents that may run at the same time. Attempts to spawn beyond this limit return an error. |
| `agents.defaults.failOnToolError` | `true` | Stop a spawned subagent when a tool execution fails. Set to `false` to return tool errors to the subagent model so it can recover within the same run. |


## Auto Compact

When a user is idle for longer than a configured threshold, nanobot **proactively** compresses the older part of the session context into a summary while keeping a recent legal suffix of live messages. This reduces token cost and first-token latency when the user returns — instead of re-processing a long stale context with an expired KV cache, the model receives a compact summary, the most recent live context, and fresh input.

```json
{
  "agents": {
    "defaults": {
      "idleCompactAfterMinutes": 15
    }
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `agents.defaults.idleCompactAfterMinutes` | `15` | Minutes of idle time before auto-compaction starts. Set to `0` to disable. The default is close to a typical LLM KV cache expiry window, so stale sessions get compacted before the user returns. |

`sessionTtlMinutes` remains accepted as a legacy alias for backward compatibility, but `idleCompactAfterMinutes` is the preferred config key going forward.

How it works:
1. **Idle detection**: On each idle tick (~1 s), checks all sessions for expiration.
2. **Background compaction**: Idle sessions summarize the older live prefix via LLM and keep the most recent legal suffix (currently 8 messages).
3. **Summary injection**: When the user returns, the summary is injected as runtime context (one-shot, not persisted) alongside the retained recent suffix.
4. **Restart-safe resume**: The summary is also mirrored into session metadata so it can still be recovered after a process restart.

> [!NOTE]
> Mental model: "summarize older context, keep the freshest live turns, **and overwrite the session file with the compact form.**" It is not a full `session.clear()`, but it is a write — not a soft cursor move.
>
> Concretely, auto compact rewrites `sessions/<key>.jsonl` in place: older messages (including their structured `tool_calls` / `tool_call_id` / `reasoning_content`) are replaced by just the retained recent suffix (currently 8 messages), while the archived prefix is preserved only as a plain-text summary appended to `memory/history.jsonl` (or a `[RAW] ...` flattened dump if LLM summarization fails). The original structured JSON of those turns is no longer recoverable from the session file.
>
> This differs from the **token-driven soft consolidation** that fires when a prompt exceeds the context budget: that path only advances an internal `last_consolidated` cursor and leaves the session file untouched, so the raw tool-call trail stays on disk and can still be replayed or audited. If you rely on that trail for debugging or auditing, set `idleCompactAfterMinutes` to `0` and let only the token-driven path run.

## Timezone

Time is context. Context should be precise.

By default, nanobot uses `UTC` for runtime time context. If you want the agent to think in your local time, set `agents.defaults.timezone` to a valid [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones):

```json
{
  "agents": {
    "defaults": {
      "timezone": "Asia/Shanghai"
    }
  }
}
```

This affects runtime time strings shown to the model, such as runtime context. It also becomes the default timezone for cron schedules when a cron expression omits `tz`, and for one-shot `at` times when the ISO datetime has no explicit offset.

Common examples: `UTC`, `America/New_York`, `America/Los_Angeles`, `Europe/London`, `Europe/Berlin`, `Asia/Tokyo`, `Asia/Shanghai`, `Asia/Singapore`, `Australia/Sydney`.

> Need another timezone? Browse the full [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

## Unified Session

By default, each channel × chat ID combination gets its own session. If you use nanobot across multiple channels (e.g. Telegram + Discord + CLI) and want them to share the same conversation, enable `unifiedSession`:

```json
{
  "agents": {
    "defaults": {
      "unifiedSession": true
    }
  }
}
```

When enabled, all incoming messages — regardless of which channel they arrive on — are routed into a single shared session. Switching from Telegram to Discord (or any other channel) continues the same conversation seamlessly.

| Behavior | `false` (default) | `true` |
|----------|-------------------|--------|
| Session key | `channel:chat_id` | `unified:default` |
| Cross-channel continuity | No | Yes |
| `/new` clears | Current channel session | Shared session |
| `/stop` finds tasks | By channel session | By shared session |
| Existing `session_key_override` (e.g. Telegram thread) | Respected | Still respected — not overwritten |

> This is designed for single-user, multi-device setups. It is **off by default** — existing users see zero behavior change.

## Disabled Skills

nanobot ships with built-in skills, and your workspace can also define custom skills under `skills/`. If you want to hide specific skills from the agent, set `agents.defaults.disabledSkills` to a list of skill directory names:

```json
{
  "agents": {
    "defaults": {
      "disabledSkills": ["github", "weather"]
    }
  }
}
```

Disabled skills are excluded from the main agent's skill summary, from always-on skill injection, and from subagent skill summaries. This is useful when some bundled skills are unnecessary for your deployment or should not be exposed to end users.

| Option | Default | Description |
|--------|---------|-------------|
| `agents.defaults.disabledSkills` | `[]` | List of skill directory names to exclude from loading. Applies to both built-in skills and workspace skills. |

## Tool Hint Max Length

Tool hints are the short progress messages shown when the agent calls tools (e.g. `$ cd …/project && npm test`). By default, these are truncated at 40 characters, which can make long commands hard to read.

Set `agents.defaults.toolHintMaxLength` to control the truncation threshold:

```json
{
  "agents": {
    "defaults": {
      "toolHintMaxLength": 120
    }
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `agents.defaults.toolHintMaxLength` | `40` | Maximum characters for tool hint display. Range: 20–500. Higher values show more of the command or path; lower values keep hints compact. |
