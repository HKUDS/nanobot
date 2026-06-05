# Providers and Models

Use this page when the first reply fails because of provider/model mismatch, or
when you want to move beyond the default OpenRouter example.

For every setup, answer three questions:

1. Which provider owns the credential or endpoint?
2. What model name does that provider expect?
3. Does the provider need `apiKey`, `apiBase`, OAuth login, cloud credentials,
   or only a local server URL?

Pin `agents.defaults.provider` while setting up. You can switch back to
`"auto"` later, but explicit provider selection makes failures easier to
diagnose.

## Minimal Shape

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

The provider config gives nanobot credentials and endpoint details. The agent
defaults choose which provider/model to use for normal turns.

## Common Provider Patterns

### OpenRouter Gateway

Good first setup for global users and mixed model families.

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

Use the model ID exactly as OpenRouter lists it.

### Anthropic Direct

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  },
  "agents": {
    "defaults": {
      "provider": "anthropic",
      "model": "claude-opus-4-5"
    }
  }
}
```

Anthropic direct uses the native Anthropic provider. Do not use an OpenRouter
model ID unless the provider is OpenRouter.

### OpenAI Direct

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}"
    }
  },
  "agents": {
    "defaults": {
      "provider": "openai",
      "model": "gpt-5"
    }
  }
}
```

`providers.openai.apiType` may be set when you need to force a specific OpenAI
API surface. Other providers reject `apiType`; leave it unset outside
`providers.openai`. Replace the model with a model ID available to your OpenAI
account.

### Custom OpenAI-Compatible Endpoint

Use `custom` when the endpoint is OpenAI-compatible but not represented by a
named provider.

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://example.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "provider": "custom",
      "model": "provider-model-name"
    }
  }
}
```

`custom` does not infer a default base URL. Set `apiBase`.

### Ollama

Start Ollama separately, then point nanobot at the OpenAI-compatible endpoint.

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
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

Most Ollama setups do not require an API key.

### vLLM or Other Local OpenAI-Compatible Server

```json
{
  "providers": {
    "vllm": {
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY"
    }
  },
  "agents": {
    "defaults": {
      "provider": "vllm",
      "model": "served-model-name"
    }
  }
}
```

Some OpenAI-compatible local servers require any non-empty API key even when
they do not validate it.

### LM Studio

```json
{
  "providers": {
    "lmStudio": {
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

Config keys may be camelCase or snake_case. Provider names in
`agents.defaults.provider` should use the registry name, such as `lm_studio`.

### AWS Bedrock

Bedrock can use the AWS credential chain, profile, region, or Bedrock bearer
token depending on your AWS setup.

```json
{
  "providers": {
    "bedrock": {
      "region": "us-east-1",
      "profile": "default"
    }
  },
  "agents": {
    "defaults": {
      "provider": "bedrock",
      "model": "anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

See [`configuration.md#providers`](./configuration.md#providers) for
Bedrock-specific notes.

### OAuth Providers

Some providers do not use API keys in `config.json`.

```bash
nanobot provider login openai-codex
nanobot provider login github-copilot
```

Then explicitly select the provider and model in config. OAuth providers are
not valid automatic fallbacks.

## Provider Resolution

The effective model parameters come from:

1. `agents.defaults.modelPreset`, if set;
2. otherwise `agents.defaults.model`, `provider`, `maxTokens`,
   `contextWindowTokens`, `temperature`, and related fields.

Provider selection follows this practical rule:

- Explicit `provider` wins.
- `provider: "auto"` tries model-name keywords, configured keys, local base
  URLs, and gateway providers.
- Gateway providers such as OpenRouter and AiHubMix can route many model
  families, so the model name must be valid for that gateway.
- Local providers should normally be explicit because generic local model names
  such as `llama3.2` do not always contain provider keywords.

## Model Presets

Use presets when you switch models at runtime or from chat commands.

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4-5",
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

The preset name `default` is reserved for the implicit `agents.defaults`
settings.

## Fallback Models

Fallbacks are useful for transient provider failures, rate limits, or model
availability issues. Keep fallbacks compatible with the task size and tool use.

```json
{
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-5",
      "fallbackModels": [
        {
          "provider": "openrouter",
          "model": "anthropic/claude-sonnet-4-5",
          "maxTokens": 8192,
          "contextWindowTokens": 65536
        }
      ]
    }
  }
}
```

You can also reference named presets in `fallbackModels`.

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
| provider not found | `agents.defaults.provider` is misspelled; use registry names such as `openrouter`, `anthropic`, `ollama`, `vllm`, `lm_studio` |
| works in CLI but not chat app | Provider is fine; debug gateway/channel setup in [`chat-apps.md`](./chat-apps.md) or [`troubleshooting.md`](./troubleshooting.md) |

For the complete provider table and advanced provider-specific notes, see
[`configuration.md#providers`](./configuration.md#providers).
