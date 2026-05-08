# Configuration

Config file: `~/.nanobot/config.json`

> [!NOTE]
> If your config file is older than the current schema, you can refresh it without overwriting your existing values:
> run `nanobot onboard`, then answer `N` when asked whether to overwrite the config.
> nanobot will merge in missing default fields and keep your current settings.

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

For **systemd** deployments, use `EnvironmentFile=` in the service unit to load variables from a file that only the deploying user can read:

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

## Providers

> [!TIP]
> - **Voice transcription**: Voice messages (Telegram, WhatsApp) are automatically transcribed using Whisper. By default Groq is used (free tier). Set `"transcriptionProvider": "openai"` under `channels` to use OpenAI Whisper instead, and optionally set `"transcriptionLanguage": "en"` (or another ISO-639-1 code) for more accurate transcription. The API key is picked from the matching provider config.
> - **MiniMax Coding Plan**: Exclusive discount links for the nanobot community: [Overseas](https://platform.minimax.io/subscribe/coding-plan?code=9txpdXw04g&source=link) · [Mainland China](https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link)
> - **MiniMax (Mainland China)**: If your API key is from MiniMax's mainland China platform (minimaxi.com), set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **MiniMax thinking mode**: Use `providers.minimaxAnthropic` when you want `reasoningEffort` / thinking mode. MiniMax exposes that capability through its Anthropic-compatible endpoint, so nanobot keeps it as a separate provider instead of guessing MiniMax-specific thinking parameters on the generic OpenAI-compatible `minimax` endpoint. It uses the same `MINIMAX_API_KEY`. Default Anthropic-compatible base URL: `https://api.minimax.io/anthropic`; for mainland China use `https://api.minimaxi.com/anthropic`.
> - **VolcEngine / BytePlus Coding Plan**: Use dedicated providers `volcengineCodingPlan` or `byteplusCodingPlan` instead of the pay-per-use `volcengine` / `byteplus` providers.
> - **Zhipu Coding Plan**: If you're on Zhipu's coding plan, set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **Alibaba Cloud BaiLian**: If you're using Alibaba Cloud BaiLian's OpenAI-compatible endpoint, set `"apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"` in your dashscope provider config.
> - **Step Fun (Mainland China)**: If your API key is from Step Fun's mainland China platform (stepfun.com), set `"apiBase": "https://api.stepfun.com/v1"` in your stepfun provider config.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint | — |
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| `huggingface` | LLM (Hugging Face Inference Providers) | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `volcengine` | LLM (VolcEngine, pay-per-use) | [Coding Plan](https://www.volcengine.com/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [volcengine.com](https://www.volcengine.com) |
| `byteplus` | LLM (VolcEngine international, pay-per-use) | [Coding Plan](https://www.byteplus.com/en/activity/codingplan?utm_campaign=nanobot&utm_content=nanobot&utm_medium=devrel&utm_source=OWO&utm_term=nanobot) · [byteplus.com](https://www.byteplus.com) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM (Azure OpenAI) | [portal.azure.com](https://portal.azure.com) |
| `bedrock` | LLM (AWS Bedrock Converse, Claude/Nova/Llama/etc.) | [aws.amazon.com/bedrock](https://aws.amazon.com/bedrock/) |
| `openai` | LLM + Voice transcription (Whisper) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + Voice transcription (Whisper, default) | [console.groq.com](https://console.groq.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `minimax_anthropic` | LLM (MiniMax Anthropic-compatible endpoint, thinking mode) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM (API gateway, access to all models) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `mimo` | LLM (MiMo) | [platform.xiaomimimo.com](https://platform.xiaomimimo.com) |
| `longcat` | LLM (LongCat) | [longcat.chat](https://longcat.chat/platform/docs/zh/) |
| `ollama` | LLM (local, Ollama) | — |
| `lm_studio` | LLM (local, LM Studio) | — |
| `mistral` | LLM | [docs.mistral.ai](https://docs.mistral.ai/) |
| `stepfun` | LLM (Step Fun/阶跃星辰) | [platform.stepfun.com](https://platform.stepfun.com) |
| `ovms` | LLM (local, OpenVINO Model Server) | [docs.openvino.ai](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |
| `openai_codex` | LLM (Codex, OAuth) | `nanobot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |
| `qianfan` | LLM (Baidu Qianfan) | [cloud.baidu.com](https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26) |

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
  "agents": {
    "defaults": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0",
      "reasoningEffort": null
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
  "agents": {
    "defaults": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0",
      "reasoningEffort": null
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
  "agents": {
    "defaults": {
      "provider": "bedrock",
      "model": "bedrock/amazon.nova-lite-v1:0"
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
  "agents": {
    "defaults": {
      "provider": "bedrock",
      "model": "bedrock/global.anthropic.claude-opus-4-7",
      "reasoningEffort": "medium",
      "maxTokens": 8192
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

Codex uses OAuth instead of API keys. Requires a ChatGPT Plus or Pro account.
No `providers.openaiCodex` block is needed in `config.json`; `nanobot provider login` stores the OAuth session outside config.

**1. Login:**
```bash
nanobot provider login openai-codex
```

**2. Set model** (merge into `~/.nanobot/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
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
<summary><b>GitHub Copilot (OAuth)</b></summary>

GitHub Copilot uses OAuth instead of API keys. Requires a [GitHub account with a plan](https://github.com/features/copilot/plans) configured.
No `providers.githubCopilot` block is needed in `config.json`; `nanobot provider login` stores the OAuth session outside config.

**1. Login:**
```bash
nanobot provider login github-copilot
```

**2. Set model** (merge into `~/.nanobot/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "github-copilot/gpt-4.1"
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
<summary><b>LongCat (OpenAI-compatible)</b></summary>

LongCat is available through nanobot's built-in OpenAI-compatible provider flow.
The default API base already points to `https://api.longcat.chat/openai/v1`, so you
usually only need to set `apiKey`.

```json
{
  "providers": {
    "longcat": {
      "apiKey": "${LONGCAT_API_KEY}"
    }
  },
  "agents": {
    "defaults": {
      "provider": "longcat",
      "model": "LongCat-Flash-Chat"
    }
  }
}
```

Official model names include `LongCat-Flash-Chat`, `LongCat-Flash-Thinking`,
`LongCat-Flash-Thinking-2601`, and `LongCat-Flash-Lite`.

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
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> For local servers that don't require authentication, set `apiKey` to `null`.
>
> `custom` is the right choice for providers that expose an OpenAI-compatible **chat completions** API. It does **not** force third-party endpoints onto the OpenAI/Azure **Responses API**.
>
> If your proxy or gateway is specifically Responses-API-compatible, use the `azure_openai` provider shape instead and point `apiBase` at that endpoint:
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
>   "agents": {
>     "defaults": {
>       "provider": "azure_openai",
>       "model": "your-model-name"
>     }
>   }
> }
> ```
>
> In short: **chat-completions-compatible endpoint → `custom`**; **Responses-compatible endpoint → `azure_openai`**.

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

</details>

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
  "agents": {
    "defaults": {
      "provider": "ollama",
      "model": "llama3.2"
    }
  }
}
```

> `provider: "auto"` also works when `providers.ollama.apiBase` is configured, but setting `"provider": "ollama"` is the clearest option.

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
  "agents": {
    "defaults": {
      "provider": "lm_studio",
      "model": "local-model"
    }
  }
}
```

> **Note:** Set `apiKey` to `null` for LM Studio since it runs locally and doesn't require authentication. The model name should match what's shown in the LM Studio UI.
> `provider: "auto"` also works when `providers.lm_studio.apiBase` is configured, but setting `"provider": "lm_studio"` is the clearest option.

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
  "agents": {
    "defaults": {
      "provider": "ovms",
      "model": "openai/gpt-oss-20b"
    }
  }
}
```

> OVMS is a local server — no API key required. Supports tool calling (`--tool_parser gptoss`), reasoning (`--reasoning_parser gptoss`), and streaming.
> See the [official OVMS docs](https://docs.openvino.ai/2026/model-server/ovms_docs_llm_quickstart.html) for more details.
</details>

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

*Model:*
```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary><b>Adding a New Provider (Developer Guide)</b></summary>

nanobot uses a **Provider Registry** (`nanobot/providers/registry.py`) as the single source of truth.
Adding a new provider only takes **2 steps** — no if-elif chains to touch.

**Step 1.** Add a `ProviderSpec` entry to `PROVIDERS` in `nanobot/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",                   # config field name
    keywords=("myprovider", "mymodel"),  # model-name keywords for auto-matching
    env_key="MYPROVIDER_API_KEY",        # env var name
    display_name="My Provider",          # shown in `nanobot status`
    default_api_base="https://api.myprovider.com/v1",  # OpenAI-compatible endpoint
)
```

**Step 2.** Add a field to `ProvidersConfig` in `nanobot/config/schema.py`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

That's it! Environment variables, model routing, config matching, and `nanobot status` display will all work automatically.

**Common `ProviderSpec` options:**

| Field | Description | Example |
|-------|-------------|---------|
| `default_api_base` | OpenAI-compatible base URL | `"https://api.deepseek.com"` |
| `env_extras` | Additional env vars to set | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | Per-model parameter overrides | `(("kimi-k2.5", {"temperature": 1.0}), ("kimi-k2.6", {"temperature": 1.0}),)` |
| `is_gateway` | Can route any model (like OpenRouter) | `True` |
| `detect_by_key_prefix` | Detect gateway by API key prefix | `"sk-or-"` |
| `detect_by_base_keyword` | Detect gateway by API base URL | `"openrouter"` |
| `strip_model_prefix` | Strip provider prefix before sending to gateway | `True` (for AiHubMix) |
| `supports_max_completion_tokens` | Use `max_completion_tokens` instead of `max_tokens`; required for providers that reject both being set simultaneously (e.g. VolcEngine) | `True` |

</details>

## Channel Settings

Global settings that apply to all channels. Configure under the `channels` section in `~/.nanobot/config.json`:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "sendMaxRetries": 3,
    "transcriptionProvider": "groq",
    "transcriptionLanguage": null,
    "telegram": { ... }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `sendProgress` | `true` | Stream agent's text progress to the channel |
| `sendToolHints` | `false` | Stream tool-call hints (e.g. `read_file("…")`) |
| `sendMaxRetries` | `3` | Max delivery attempts per outbound message, including the initial send (0-10 configured, minimum 1 actual attempt) |
| `transcriptionProvider` | `"groq"` | Voice transcription backend: `"groq"` (free tier, default) or `"openai"`. API key is auto-resolved from the matching provider config. |
| `transcriptionLanguage` | `null` | Optional ISO-639-1 language hint for audio transcription, e.g. `"en"`, `"ko"`, `"ja"`. |

`sendProgress` and `sendToolHints` can also be overridden per channel. The
global values stay as defaults for channels that do not set their own value:

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

If you need to allow trusted private ranges such as Tailscale / CGNAT addresses, you can explicitly exempt them from SSRF blocking with `tools.ssrfWhitelist`:

```json
{
  "tools": {
    "ssrfWhitelist": ["100.64.0.0/10"]
  }
}
```

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
| `searxng` | `baseUrl` | `SEARXNG_BASE_URL` | Yes (self-hosted) |
| `duckduckgo` (default) | — | — | Yes |

**Brave:**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA..."
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
        "apiKey": "tvly-..."
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
        "apiKey": "jina_..."
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
        "apiKey": "your-kagi-api-key"
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
        "apiKey": "YOUR_OLOSTEP_API_KEY"
      }
    }
  }
}
```

You can also set `OLOSTEP_API_KEY` in the environment instead of storing it in config.

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
| `provider` | string | `"duckduckgo"` | Search backend: `brave`, `tavily`, `jina`, `searxng`, `duckduckgo` |
| `apiKey` | string | `""` | API key for Brave or Tavily |
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

Image generation is configured under `tools.imageGeneration` and uses provider credentials from `providers.openrouter` or `providers.aihubmix`.

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

- Omit `enabledTools`, or set it to `["*"]`, to register all tools.
- Set `enabledTools` to `[]` to register no tools from that server.
- Set `enabledTools` to a non-empty list of names to register only that subset.

MCP tools are automatically discovered and registered on startup. The LLM can use them alongside built-in tools — no extra configuration needed.




## Security

> [!TIP]
> For production deployments, set `"restrictToWorkspace": true` and `"tools.exec.sandbox": "bwrap"` in your config to sandbox the agent.
> In `v0.1.4.post3` and earlier, an empty `allowFrom` allowed all senders. Since `v0.1.4.post4`, empty `allowFrom` denies all access by default. To allow all senders, set `"allowFrom": ["*"]`.

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | When `true`, restricts **all** agent tools (shell, file read/write/edit, list) to the workspace directory. Prevents path traversal and out-of-scope access. |
| `tools.exec.sandbox` | `""` | Sandbox backend for shell commands. Set to `"bwrap"` to wrap exec calls in a [bubblewrap](https://github.com/containers/bubblewrap) sandbox — the process can only see the workspace (read-write) and media directory (read-only); config files and API keys are hidden. Automatically enables `restrictToWorkspace` for file tools. **Linux only** — requires `bwrap` installed (`apt install bubblewrap`; pre-installed in the Docker image). Not available on macOS or Windows (bwrap depends on Linux kernel namespaces). |
| `tools.exec.enable` | `true` | When `false`, the shell `exec` tool is not registered at all. Use this to completely disable shell command execution. |
| `tools.exec.pathAppend` | `""` | Extra directories to append to `PATH` when running shell commands (e.g. `/usr/sbin` for `ufw`). |
| `channels.*.allowFrom` | `[]` (deny all) | Whitelist of user IDs. Empty denies all; use `["*"]` to allow everyone. |

**Docker security**: The official Docker image runs as a non-root user (`nanobot`, UID 1000) with bubblewrap pre-installed. When using `docker-compose.yml`, the container drops all Linux capabilities except `SYS_ADMIN` (required for bwrap's namespace isolation).


## Subagent Concurrency

By default, nanobot only allows one spawned subagent at a time. When the limit is
reached, the `spawn` tool returns an error so the agent can decide to wait or
rearrange its work. This protects local LLM servers from loading multiple KV caches
at once. If your provider can handle more parallel work, raise the limit:

```json
{
  "agents": {
    "defaults": {
      "maxConcurrentSubagents": 2
    }
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `agents.defaults.maxConcurrentSubagents` | `1` | Maximum number of spawned subagents that may run at the same time. Attempts to spawn beyond this limit return an error. |


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
| `agents.defaults.idleCompactAfterMinutes` | `0` (disabled) | Minutes of idle time before auto-compaction starts. Set to `0` to disable. Recommended: `15` — close to a typical LLM KV cache expiry window, so stale sessions get compacted before the user returns. |

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
> This differs from the **token-driven soft consolidation** that fires when a prompt exceeds the context budget: that path only advances an internal `last_consolidated` cursor and leaves the session file untouched, so the raw tool-call trail stays on disk and can still be replayed or audited. If you rely on that trail for debugging or auditing, leave `idleCompactAfterMinutes` at the default `0` and let only the token-driven path run.

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

This affects runtime time strings shown to the model, such as runtime context and heartbeat prompts. It also becomes the default timezone for cron schedules when a cron expression omits `tz`, and for one-shot `at` times when the ISO datetime has no explicit offset.

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
