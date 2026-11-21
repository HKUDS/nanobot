# Providers and Models

Use this page when the first reply fails because of provider/model mismatch, or when you want to adapt the concrete setup example to a different provider. If you already know which provider you want and only need a pasteable setup, use [`provider-cookbook.md`](./provider-cookbook.md).

For normal local setup, open **Settings → Models → New preset**, select your provider (or click **Add provider**), and pick a model. Expand **Manual configuration** below if you manage `config.json` directly or deploy headlessly.

> [!NOTE]
> For OAuth providers (OpenAI Codex, xAI Grok, and GitHub Copilot), the model picker fetches available models from your signed-in account. If your session expires, click **Sign in again**; if a fallback model handles a reply, a banner above the composer lets you know.

For every setup, make sure three things match:

1. Which provider owns the credential or endpoint.
2. Which exact model ID that provider expects.
3. What authentication it uses (API key, OAuth sign-in, cloud credentials, or a local server URL).

Prefer creating a named preset in **Settings → Models** and pinning its `provider` explicitly—it makes `/model` switching and fallbacks much easier to manage.

## Choose a Provider Without Guessing

The docs show concrete provider names so the JSON is copyable, not because nanobot ranks providers. Start from the service or endpoint you actually control:

| If you have... | Configure... |
|---|---|
| An API key from a hosted provider or gateway | That provider's `providers.<name>.apiKey`, then a preset with that provider name and a model ID from that service. |
| An OpenCode Zen or Go key | `providers.opencodeZen.apiKey` or `providers.opencodeGo.apiKey`, then a preset with `provider: "opencode_zen"` or `provider: "opencode_go"`. |
| A company proxy or regional endpoint | The matching provider block plus `apiBase` if the proxy gives you a URL. |
| A local OpenAI-compatible server | A local provider block such as `ollama`, `vllm`, `lmStudio`, or `custom`, usually with `apiBase`. |
| An OAuth-based account | Choose the provider in **Settings → Models**, complete its sign-in flow, and select it explicitly in a preset. |
| No provider yet | Follow [Prepare your model details](./start-without-technical-background.md#2-prepare-your-model-details) for an API account example, or the [Ollama recipe](./provider-cookbook.md#recipe-ollama-local-model) for local models. Check account access, pricing, regional availability, and privacy requirements before choosing. |

## Minimal Shape

Create and select a preset through **Settings → Models** as described above. The JSON alternative shows where those values are stored.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

The provider config gives nanobot credentials and endpoint details. The model preset names the provider/model pair. The agent defaults choose which named preset to use for normal turns. Replace the example provider and model together; mixing an API key from one provider with a model ID from another is the most common first-run failure.

## Provider, Model, API Key, and Base URL

These fields answer different questions:

| Field | Where it lives | Meaning |
|---|---|---|
| `provider` | `modelPresets.<name>.provider` | Which nanobot provider adapter should send the request. |
| `model` | `modelPresets.<name>.model` | The model ID expected by that provider or gateway. |
| `apiKey` | `providers.<provider>.apiKey` | Credential for that provider. Use `${ENV_VAR}` for secrets. |
| `apiBase` | `providers.<provider>.apiBase` | HTTP base URL of the provider endpoint. |
| `use_proxy` | `providers.<provider>.useProxy` | Use the shared `network.proxy` address for this provider. Supported for OpenAI-compatible providers, Anthropic Messages, OpenAI Codex, and xAI OAuth. |

You usually omit `apiBase` for hosted built-in providers such as OpenRouter, Anthropic direct, OpenAI direct, Groq, or Bedrock because nanobot knows their default endpoints. Set `apiBase` for `custom`, local OpenAI-compatible servers, provider proxies, regional endpoints, or subscription endpoints. Include the API version path when the endpoint requires it, for example `https://api.example.com/v1` or `http://localhost:11434/v1`.

Use `proxy` when one provider must send HTTP traffic through a proxy without changing process-wide `HTTP_PROXY` / `HTTPS_PROXY`. Supported providers include `openai`, `custom`, named custom providers, OpenRouter-style gateways, local OpenAI-compatible servers, Anthropic Messages, `openai_codex`, and `xai_grok`. For OAuth providers, this also covers exchanging and refreshing tokens. `bedrock`, `azure_openai`, and `github_copilot` reject `proxy`; use their endpoint-specific configuration instead.

Tool calling requires a model and endpoint that return structured tool calls (if replies show raw `<tool_call>` or `<function=...>` text, enable your server's tool-call parser or switch to a tool-capable model).

Large image attachments are automatically resized/compressed as needed before sending to your model provider while keeping your original files untouched.

## Common Provider Patterns

### OpenRouter Gateway

Gateway-style setup for model IDs served through OpenRouter.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Use the model ID exactly as OpenRouter lists it.

To opt into OpenRouter server-managed search and fetch, add:

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "openrouter": {
      "extraBody": {
        "tools": [
          { "type": "openrouter:web_search" },
          { "type": "openrouter:web_fetch" }
        ]
      }
    }
  }
}
```

</details>

Chat Completions-compatible OpenRouter [server tools](https://openrouter.ai/docs/guides/features/server-tools), such as those above, are appended to nanobot's generated functions. This keeps unrelated local tools such as `write_file` available in the same request. Responses-only server tools require an API surface that the OpenRouter provider does not currently enable.

### OrcaRouter Gateway

[OrcaRouter](https://www.orcarouter.ai) is an OpenAI-compatible model routing gateway. Configure the built-in `orcarouter` provider and use a model ID from OrcaRouter's catalog:

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "orcarouter": {
      "apiKey": "${ORCAROUTER_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "orcarouter",
      "model": "orcarouter/auto",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Use the model ID exactly as OrcaRouter lists it. `orcarouter/auto` routes to a suitable upstream automatically; explicit IDs such as `anthropic/claude-sonnet-4.6` or `openai/gpt-5` are also accepted. OrcaRouter API keys start with `sk-orca-`. The WebUI can load the account's model catalog after the API key is saved under **Settings → Models**.

### Eden AI Gateway

Eden AI exposes an OpenAI-compatible chat-completions endpoint at `https://api.edenai.run/v3`. Configure the built-in `edenai` provider and use the full `provider/model` identifier listed by Eden AI:

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "edenai": {
      "apiKey": "${EDENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "edenai",
      "model": "anthropic/claude-sonnet-4-5",
      "maxTokens": 8192
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Nanobot sends the model ID unchanged, including its provider prefix. Use Eden AI's [model listing](https://www.edenai.co/docs/v3/llms/listing-models) to choose a currently available model. The WebUI can also load that catalog after the Eden AI API key is saved under **Settings → Models**.

### OpenCode Zen and Go

OpenCode Zen and OpenCode Go are OpenCode-managed gateways for coding-agent models. They share `OPENCODE_API_KEY`, but use separate provider config keys and default base URLs in nanobot.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "opencodeZen": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "opencode_zen",
      "model": "opencode/deepseek-v4-pro",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

For OpenCode Go, switch the provider block and preset:

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "opencodeGo": {
      "apiKey": "${OPENCODE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "opencode_go",
      "model": "opencode-go/deepseek-v4-flash",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  }
}
```

</details>

OpenCode documents model IDs with `opencode/<model-id>` for Zen and `opencode-go/<model-id>` for Go. nanobot accepts those prefixes and strips them before sending the request to OpenCode. Choose a model served through Chat Completions or Responses by the matching Zen or Go service; models that require Anthropic Messages or another provider-specific API are not supported by these connections.

Leave API selection on **Auto** for OpenCode Go's `muse-spark-1.2-contributor` and `muse-spark-1.3-contributor`; these models use Responses automatically. Other models use Chat Completions by default. If another model requires Responses, select it in the preset's **Advanced options** only when the service supports it. See [preset API settings](./configuration.md#preset-request-api).

### Anthropic Direct

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Anthropic direct uses the native Anthropic provider. Do not use an OpenRouter model ID unless the provider is OpenRouter.

If you use an Anthropic-compatible proxy, keep the provider as `anthropic` and override `apiBase`:

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}",
      "apiBase": "https://anthropic-proxy.example.com"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  }
}
```

</details>

For a named custom provider serving Anthropic Messages, set `providers.<name>.api.supportedApis` to `["anthropic_messages"]`. Auto presets then use Messages with that connection's credentials and endpoint.

### OpenAI Direct

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "openai",
      "model": "gpt-5",
      "maxTokens": 8192,
      "contextWindowTokens": 128000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Replace the model with a model ID available to your account. Leave API selection on Auto unless you need to choose Chat Completions or Responses in the preset's **Advanced options**. See [preset API settings](./configuration.md#preset-request-api) for WebUI and JSON configuration. `providers.openai.api` sets the connection default; explicit presets override it.

### DeepSeek

Select **DeepSeek** in **Settings → Models**. Use `deepseek-flash` for text and image input, or `deepseek-v4-pro` for text-only input. The official service also accepts `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` as Flash aliases; see [current model details](https://api-docs.deepseek.com/quick_start/pricing) for availability.

Known Flash and Pro models offer `none`, `low`, `high`, and `max` reasoning settings. Leave reasoning effort empty to follow the provider default (currently thinking enabled at `high`), or choose `none` to disable thinking. The output budget covers both reasoning and the final answer.

**Auto** uses Responses for these models at the official endpoint (`https://api.deepseek.com`, with or without `/v1`). With a proxy, keep the model ID it documents: `deepseek-flash` defaults to Chat Completions on other endpoints, while the V4 names above default to Responses. Select Responses explicitly for `deepseek-flash` only if your proxy supports it; see [preset API settings](./configuration.md#preset-request-api).

For web search, configure nanobot's [web search tool](./guides/configure-web-search.md). Selecting a DeepSeek model does not enable DeepSeek-hosted search.

### Custom OpenAI-Compatible Endpoint

The `custom` provider fits one OpenAI-compatible endpoint that is not represented by a named provider.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "custom",
      "model": "provider-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

`custom` does not infer a default base URL. Set `apiBase`.

If you have more than one custom OpenAI-compatible endpoint, give each endpoint its own provider key under `providers` and use that same key in the model preset. The key can be a name that makes sense in your environment, such as `companyProxy`, `tenant-a`, or `dev-local`.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "companyProxy": {
      "apiKey": "${COMPANY_PROXY_API_KEY}",
      "apiBase": "https://llm-proxy.example.com/v1"
    },
    "tenant-a": {
      "apiBase": "https://tenant-a.example.com/v1"
    }
  },
  "modelPresets": {
    "company": {
      "provider": "companyProxy",
      "model": "gpt-4o-mini",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    },
    "tenantA": {
      "provider": "tenant-a",
      "model": "served-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "company"
    }
  }
}
```

</details>

Custom provider keys define direct connections. Without an API declaration, they use OpenAI-compatible Chat Completions. `apiBase` is required because nanobot cannot know the endpoint URL. `apiKey` is optional for local servers or private proxies that do not require one. Choose a name that does not conflict with a built-in provider name or alias, such as `openai`, `openai-codex`, `github-copilot`, or `lm-studio`. Declare the accepted protocols under `api` as described in [connection request APIs](./configuration.md#custom-connection-apis).

If your custom endpoint documents a nonstandard thinking toggle, set `providers.<name>.thinkingStyle` to `thinking_type`, `enable_thinking`, or `reasoning_split`; nanobot then maps `reasoningEffort` onto that provider-specific request body. Leave it unset for ordinary OpenAI-compatible endpoints.

### ModelScope

ModelScope (魔搭社区) exposes an OpenAI-compatible LLM endpoint plus a separate async image generation API. Both are covered by the built-in `modelscope` provider.

Create a ModelScope [access token](https://modelscope.cn/my/myaccesstoken), then choose a model whose page exposes API-Inference. The example below uses [`Qwen/Qwen3-32B`](https://modelscope.cn/models/Qwen/Qwen3-32B); hosted availability and quotas are controlled by ModelScope. See the official [API-Inference guide](https://modelscope.cn/docs/model-service/API-Inference/intro) for current service details.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "modelscope": {
      "apiKey": "${MODELSCOPE_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "modelscope",
      "model": "Qwen/Qwen3-32B",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Use an inference-enabled model ID exactly as ModelScope publishes it (usually `Namespace/model-name`). The default base URL is `https://api-inference.modelscope.cn/v1`; override `providers.modelscope.apiBase` only if your account routes through a different host. Chat model IDs may optionally be prefixed with `modelscope/`; nanobot strips that routing prefix before sending the request.

ModelScope image generation reuses the same provider key but is configured under `tools.imageGeneration`, not in a model preset:

<details>
<summary>Manual configuration</summary>

```json
{
  "tools": {
    "imageGeneration": {
      "enabled": true,
      "provider": "modelscope",
      "model": "Qwen/Qwen-Image-2512"
    }
  }
}
```

</details>

Use the image model's exact ModelScope ID without a leading `modelscope/`; the image client sends this value unchanged and handles ModelScope's async submit/poll flow. The example uses [`Qwen/Qwen-Image-2512`](https://modelscope.cn/models/Qwen/Qwen-Image-2512). See [Image Generation](./image-generation.md#modelscope) for supported sizes, aspect ratios, and the complete provider configuration.

### Ollama

Prepare Ollama using the [local model recipe](./provider-cookbook.md#recipe-ollama-local-model), then point nanobot at its OpenAI-compatible endpoint.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 4096,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Most Ollama setups do not require an API key.

Ollama renders the OpenAI-compatible messages and tools through each model's chat template. If ordinary model responses are fast but tool-using turns show low prompt cache reuse, diagnose the rendered template before changing nanobot's context or memory settings. The [Ollama prompt-cache guide](./guides/configure-ollama-prompt-cache.md) explains the log pattern and a tested `llama3.1:8b` workaround.

### vLLM or Other Local OpenAI-Compatible Server

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "vllm": {
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "vllm",
      "model": "served-model-name",
      "maxTokens": 8192,
      "contextWindowTokens": 65536
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Some OpenAI-compatible local servers require any non-empty API key even when they do not validate it.

### LM Studio

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "lmStudio": {
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "lm_studio",
      "model": "local-model",
      "maxTokens": 4096,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

Config keys may be camelCase or snake_case. Provider names in model presets should use the registry name, such as `lm_studio`.

### AWS Bedrock

Bedrock can use the AWS credential chain, profile, region, or Bedrock bearer token depending on your AWS setup.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "profile": "default"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "bedrock",
      "model": "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0",
      "maxTokens": 8192,
      "contextWindowTokens": 200000
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

</details>

See [`configuration.md#providers`](./configuration.md#providers) for Bedrock-specific notes.

### OAuth Providers

These providers use account sign-in instead of API keys in `config.json`. You can sign in through **Settings → Models** in the WebUI or from the terminal:

**OpenAI Codex**

```bash
nanobot provider login openai-codex --set-main
```

**xAI Grok (requires an eligible X Premium / Grok subscription)**

```bash
nanobot provider login xai-grok --set-main
```

Hosted X Search is enabled by default for supported Grok models and can be turned off in WebUI model settings (or via `providers.xaiGrok.extraBody.tools: []`). Credentials are stored in `~/.nanobot/auth/xai.json`.

**GitHub Copilot**

Sign in from **Settings → Models** using the device-code flow (copy the code, click **Open GitHub**, and approve—works from remote browsers too), or from the terminal:

```bash
nanobot provider login github-copilot --set-main
```

Each `--set-main` command signs in and sets that provider's default model as active. See [Provider and Model Problems](./troubleshooting.md#provider-and-model-problems) if you need proxy or headless-server login steps.

## Provider Resolution

The recommended path is a named preset selected by `agents.defaults.modelPreset`. The effective model parameters come from:

1. the named `modelPresets` entry referenced by `agents.defaults.modelPreset`;
2. otherwise the implicit `default` preset built from `agents.defaults.model`, `provider`, `maxTokens`, `contextWindowTokens`, `temperature`, and related fields.

Provider selection follows this practical rule:

- Explicit `provider` in the active preset or implicit default config wins.
- `provider: "auto"` tries model-name keywords, configured keys, local base URLs, and gateway providers.
- Gateway providers such as OpenRouter and AiHubMix can route many model families, so the model name must be valid for that gateway.
- Local providers should normally be explicit because generic local model names such as `llama3.2` do not always contain provider keywords.

### Model Name Prefixes

`family/model-name` does not always select provider `family`. Prefix-based provider inference only runs when the active provider is `"auto"`.

- Explicit provider wins: `provider: "openrouter"` with `model: "anthropic/claude-sonnet-4.5"` calls OpenRouter, not Anthropic.
- With `provider: "auto"`, a prefix matching a configured built-in or named custom provider can select that provider. Named custom prefixes are stripped before request, so `companyProxy/gpt-4o-mini` is sent upstream as `gpt-4o-mini`.
- With an explicit named custom provider, the model is sent as written; `provider: "companyProxy"` with `model: "openai/gpt-4o-mini"` sends `openai/gpt-4o-mini` to `companyProxy`.

Pin `provider` in presets when using gateway catalog IDs such as `anthropic/claude-sonnet-4.5`.

## Model Presets

Model presets are the recommended model configuration surface. Use them when you want named model choices, runtime `/model` switching, or reusable fallback targets.

When available, the selected provider's model catalog supplies reasoning-effort suggestions; you can still enter a custom value. Choosing a catalog model for a new preset can initialize its context window. Existing presets and manually entered context values are preserved, and catalog output limits do not raise the preset's output budget. See [preset fields](./configuration.md#model-presets) for configuration details.

Direct OpenAI Responses, OpenAI Codex, Azure OpenAI Responses, and eligible GitHub Copilot models can retain server-provided conversation state; [native context compaction](./configuration.md#responses-state-and-compaction) depends on provider support. The WebUI offers switches for OpenAI web search, Codex Fast mode, and Grok X Search.

<details>
<summary>Manual configuration</summary>

```json
{
  "modelPresets": {
    "fast": {
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast"
    }
  }
}
```

</details>

The preset name `default` is reserved for the implicit `agents.defaults` settings. Do not define `modelPresets.default`; use `/model default` to return to the direct `agents.defaults.*` fields in older configs.

## Fallback Models

Fallbacks are useful for transient provider failures, rate limits, or model availability issues. Keep fallbacks compatible with the task size and tool use. Prefer fallback presets so each candidate has a name and a complete provider, model, generation, and context-window configuration.

<details>
<summary>Manual configuration</summary>

```json
{
  "modelPresets": {
    "fast": {
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "localSmall": {
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 4096,
      "contextWindowTokens": 32768,
      "temperature": 0.2
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

</details>

String entries in `fallbackModels` are preset names, not raw model names. nanobot tries them in order after the active preset. Each fallback preset uses its own `provider`, `model`, `maxTokens`, `contextWindowTokens`, `temperature`, and optional `reasoningEffort`.

Use inline fallback objects only when a model is not worth naming as a preset:

<details>
<summary>Manual configuration</summary>

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

</details>

`fallbackModels` belongs under `agents.defaults`, not inside each preset. If fallback candidates use smaller context windows, nanobot builds context using the smallest window in the active chain so every candidate can receive the same prompt. See [`configuration.md#model-fallbacks`](./configuration.md#model-fallbacks) for failure conditions.

## Quick Checks

Run these before debugging a chat app:

```bash
nanobot status
nanobot agent -m "Hello!"
```

If `nanobot agent -m "Hello!"` fails:

| Symptom | Likely cause |
|---|---|
| 401, unauthorized, invalid API key | Key is missing, expired, copied with whitespace, or stored under the wrong provider |
| model not found | Model ID does not exist for the selected provider or gateway |
| connection refused | Local provider server is not running or `apiBase` points to the wrong port |
| provider not found | The active preset uses a misspelled provider; use registry names such as `openrouter`, `anthropic`, `ollama`, `vllm`, `lm_studio` |
| works in CLI but not chat app | Provider is fine; debug gateway/channel setup in [`chat-apps.md`](./chat-apps.md) or [`troubleshooting.md`](./troubleshooting.md) |

For the complete provider table and advanced provider-specific notes, see [`configuration.md#providers`](./configuration.md#providers).
