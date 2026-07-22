# Providers and Models

Use this page when the first reply fails because of provider/model mismatch, or when you want to adapt the concrete setup example to a different provider. If you already know which provider you want and only need a pasteable setup, use [`provider-cookbook.md`](./provider-cookbook.md).

For normal local setup, open **Settings → Models** in the WebUI to add provider credentials, create a model preset, and select the active model. Use the JSON below for manual deployments, local endpoints, provider-specific fields, or diagnosis.

For every setup, answer three questions:

1. Which provider owns the credential or endpoint?
2. What model name does that provider expect?
3. Does the provider need `apiKey`, `apiBase`, OAuth login, cloud credentials, or only a local server URL?

Prefer a named `modelPresets` entry for the model/provider pair, then select it with `agents.defaults.modelPreset`. Direct `agents.defaults.provider` and `agents.defaults.model` still work for existing configs, but presets make runtime `/model` switching and fallback chains clearer. Pin `provider` inside the preset while setting up; you can switch back to `"auto"` later.

## Choose a Provider Without Guessing

The docs show concrete provider names so the JSON is copyable, not because nanobot ranks providers. Start from the service or endpoint you actually control:

| If you have... | Configure... |
|---|---|
| An API key from a hosted provider or gateway | That provider's `providers.<name>.apiKey`, then a preset with that provider name and a model ID from that service. |
| An OpenCode Zen or Go key | `providers.opencodeZen.apiKey` or `providers.opencodeGo.apiKey`, then a preset with `provider: "opencode_zen"` or `provider: "opencode_go"`. |
| A company proxy or regional endpoint | The matching provider block plus `apiBase` if the proxy gives you a URL. |
| A local OpenAI-compatible server | A local provider block such as `ollama`, `vllm`, `lmStudio`, or `custom`, usually with `apiBase`. |
| An OAuth-based account | Run the matching `nanobot provider login ...` command, then select that provider explicitly in a preset. |
| No provider yet | Pick one outside nanobot based on account access, pricing, regional availability, privacy requirements, and the model IDs you need. Then come back with its key and model ID. |

## Minimal Shape

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

The provider config gives nanobot credentials and endpoint details. The model preset names the provider/model pair. The agent defaults choose which named preset to use for normal turns. Replace the example provider and model together; mixing an API key from one provider with a model ID from another is the most common first-run failure.

## Provider, Model, API Key, and Base URL

These fields answer different questions:

| Field | Where it lives | Meaning |
|---|---|---|
| `provider` | `modelPresets.<name>.provider` | Which nanobot provider adapter should send the request. |
| `model` | `modelPresets.<name>.model` | The model ID expected by that provider or gateway. |
| `apiKey` | `providers.<provider>.apiKey` | Credential for that provider. Use `${ENV_VAR}` for secrets. |
| `apiBase` | `providers.<provider>.apiBase` | HTTP base URL of the provider endpoint. |
| `proxy` | `providers.<provider>.proxy` | Optional HTTP proxy for this provider only. Supported for OpenAI-compatible providers, OpenAI Codex, and xAI OAuth. |

You usually omit `apiBase` for hosted built-in providers such as OpenRouter, Anthropic direct, OpenAI direct, Groq, or Bedrock because nanobot knows their default endpoints. Set `apiBase` for `custom`, local OpenAI-compatible servers, provider proxies, regional endpoints, or subscription endpoints. Include the API version path when the endpoint requires it, for example `https://api.example.com/v1` or `http://localhost:11434/v1`.

Use `proxy` when one provider must send HTTP traffic through a proxy without changing process-wide `HTTP_PROXY` / `HTTPS_PROXY`. This is supported for providers that use nanobot's OpenAI-compatible client, including `openai`, `custom`, named custom providers, OpenRouter-style gateways, local OpenAI-compatible servers, and similar registry entries. It is also supported for `openai_codex` and `xai_grok`, including OAuth token exchange/refresh and model requests. Native provider backends such as `anthropic`, `bedrock`, `azure_openai`, and `github_copilot` reject `proxy`; use their endpoint-specific configuration instead.

## Common Provider Patterns

### OpenRouter Gateway

Gateway-style setup for model IDs served through OpenRouter.

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

Use the model ID exactly as OpenRouter lists it.

### OpenCode Zen and Go

OpenCode Zen and OpenCode Go are OpenCode-managed gateways for coding-agent models.
They share `OPENCODE_API_KEY`, but use separate provider config keys and default base
URLs in nanobot.

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

For OpenCode Go, switch the provider block and preset:

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

OpenCode documents model IDs with `opencode/<model-id>` for Zen and
`opencode-go/<model-id>` for Go. nanobot accepts those prefixes and strips them
before sending the request to OpenCode. Use model IDs that OpenCode lists under
the `chat/completions` endpoint; models listed only under `responses`,
`messages`, or provider-specific endpoints are not handled by this
OpenAI-compatible provider path.

### Anthropic Direct

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

Anthropic direct uses the native Anthropic provider. Do not use an OpenRouter model ID unless the provider is OpenRouter.

If you use an Anthropic-compatible proxy, keep the provider as `anthropic` and override `apiBase`:

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

Arbitrary custom provider names are OpenAI-compatible only; they do not use the Anthropic Messages API request format.

### OpenAI Direct

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

`providers.openai.apiType` may be set when you need to force a specific OpenAI API surface. Other providers reject `apiType`; leave it unset outside `providers.openai`. Replace the model with a model ID available to your OpenAI account.

### Custom OpenAI-Compatible Endpoint

The `custom` provider fits one OpenAI-compatible endpoint that is not represented by a named provider.

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

`custom` does not infer a default base URL. Set `apiBase`.

If you have more than one custom OpenAI-compatible endpoint, give each endpoint its own provider key under `providers` and use that same key in the model preset. The key can be a name that makes sense in your environment, such as `companyProxy`, `tenant-a`, or `dev-local`.

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

Custom provider keys are treated as direct OpenAI-compatible providers. `apiBase` is required because nanobot cannot know the endpoint URL. `apiKey` is optional for local servers or private proxies that do not require one. Choose a name that does not conflict with a built-in provider name or alias, such as `openai`, `openai-codex`, `github-copilot`, or `lm-studio`. Do not set `apiType` on custom provider keys; `apiType` is only for `providers.openai`.

If your custom endpoint documents a nonstandard thinking toggle, set `providers.<name>.thinkingStyle` to `thinking_type`, `enable_thinking`, or `reasoning_split`; nanobot then maps `reasoningEffort` onto that provider-specific request body. Leave it unset for ordinary OpenAI-compatible endpoints.

This named custom provider path is not for Anthropic-compatible endpoints. For Anthropic-compatible proxies, use `providers.anthropic.apiBase` and set the preset provider to `anthropic`.

### Ollama

Start Ollama separately, then point nanobot at the OpenAI-compatible endpoint.

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

Most Ollama setups do not require an API key.

Ollama renders the OpenAI-compatible messages and tools through each model's chat
template. If ordinary model responses are fast but tool-using turns show low prompt
cache reuse, diagnose the rendered template before changing nanobot's context or
memory settings. The
[Ollama prompt-cache guide](./guides/configure-ollama-prompt-cache.md) explains the
log pattern and a tested `llama3.1:8b` workaround.

### vLLM or Other Local OpenAI-Compatible Server

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

Some OpenAI-compatible local servers require any non-empty API key even when they do not validate it.

### LM Studio

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

Config keys may be camelCase or snake_case. Provider names in model presets should use the registry name, such as `lm_studio`.

### AWS Bedrock

Bedrock can use the AWS credential chain, profile, region, or Bedrock bearer token depending on your AWS setup.

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

See [`configuration.md#providers`](./configuration.md#providers) for Bedrock-specific notes.

### OAuth Providers

Some providers do not use API keys in `config.json`.

For OpenAI Codex:

```bash
nanobot provider login openai-codex --set-main
```

For an eligible X Premium / Grok subscription:

```bash
nanobot provider login xai-grok --set-main
```

This selects `xai-grok/grok-4.5`. The provider reads xAI's model catalog and
exposes the hosted `x_search` tool only when the selected model advertises
`supportsBackendSearch`; otherwise the model runs without hosted X Search.
When enabled, Grok can search current X posts and return inline source links
without invoking a local nanobot tool. Credentials are stored under the
active instance's `auth/xai.json` (normally `~/.nanobot/auth/xai.json`), not in
`config.json` and not in Grok Build's credential file.

The login is xAI subscription OAuth, not X Developer OAuth. It follows the
public client contract documented and implemented by
[Grok Build](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md);
xAI may change that upstream contract independently of nanobot.

For GitHub Copilot:

```bash
nanobot provider login github-copilot --set-main
```

Each command authenticates the selected provider and makes its current default model active. OAuth providers are not valid automatic fallbacks. See [`troubleshooting.md`](./troubleshooting.md#provider-and-model-problems) for proxy, headless-login, model-name, and config-key errors.

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

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "label": "Deep",
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

The preset name `default` is reserved for the implicit `agents.defaults` settings. Do not define `modelPresets.default`; use `/model default` to return to the direct `agents.defaults.*` fields in older configs.

## Fallback Models

Fallbacks are useful for transient provider failures, rate limits, or model availability issues. Keep fallbacks compatible with the task size and tool use. Prefer fallback presets so each candidate has a name and a complete provider, model, generation, and context-window configuration.

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "deep": {
      "label": "Deep",
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "localSmall": {
      "label": "Local Small",
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

String entries in `fallbackModels` are preset names, not raw model names. nanobot tries them in order after the active preset. Each fallback preset uses its own `provider`, `model`, `maxTokens`, `contextWindowTokens`, `temperature`, and optional `reasoningEffort`.

Use inline fallback objects only when a model is not worth naming as a preset:

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
