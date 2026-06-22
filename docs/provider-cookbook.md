# Provider Cookbook

This page is for cases where you already know what you want to connect and need a pasteable setup. Each recipe shows what to set, what to run, and what a failure usually means.

If this is your first install and terminal commands are new to you, start with [`start-without-technical-background.md`](./start-without-technical-background.md). If you want the field-by-field explanation, read [`providers.md`](./providers.md) and then [`configuration.md#providers`](./configuration.md#providers).

Most examples below are snippets to merge into `~/.nanobot/config.json`. Keep any existing sections you still need, and replace placeholder keys such as `${OPENROUTER_API_KEY}` with environment-variable references or real values only on your own machine.

Recipes are examples, not rankings. Pick the recipe that matches the credential, endpoint, and model ID you already intend to use.

## Choose a Recipe

Match the recipe to the credential or endpoint you already have:

| What you have | Recipe | Must match |
|---|---|---|
| A gateway key and model IDs that include a model family path, such as `provider/model-name` | [OpenRouter Gateway](#recipe-openrouter-gateway) | API key, provider config key, preset provider, and gateway model ID |
| An OpenAI platform API key and OpenAI model ID | [OpenAI Direct](#recipe-openai-direct) | `OPENAI_API_KEY`, `provider: "openai"`, and an OpenAI model available to that account |
| An Anthropic API key and Anthropic model ID | [Anthropic Direct](#recipe-anthropic-direct) | `ANTHROPIC_API_KEY`, `provider: "anthropic"`, and a non-gateway model ID |
| An OpenAI-compatible `/v1` endpoint that is not a named nanobot provider | [Custom OpenAI-Compatible Provider](#recipe-custom-openai-compatible-provider) | `apiBase`, optional API key, and the model ID served by that endpoint |
| Ollama already running locally | [Ollama Local Model](#recipe-ollama-local-model) | Ollama `apiBase`, pulled model name, and local server availability |
| vLLM, LM Studio, or another local OpenAI-compatible server | [vLLM or LM Studio](#recipe-vllm-or-lm-studio) | Local `/v1` base URL, any required key, and served model name |
| A primary model plus one or more backups | [Fallback Presets](#recipe-fallback-presets) | Named presets in `modelPresets`, referenced from `agents.defaults.fallbackModels` |
| A working agent and a Langfuse project | [Langfuse Tracing](#recipe-langfuse-tracing) | Langfuse env vars in the same process environment that starts nanobot |

## How to Use a Recipe

1. Install nanobot and run `nanobot onboard` once so `~/.nanobot/config.json` exists. Use `nanobot onboard --wizard` if you prefer prompts over hand-editing JSON.
2. Put secrets in environment variables when possible.
3. Merge the recipe snippet into `~/.nanobot/config.json`.
4. Run `nanobot status`.
5. Run `nanobot agent -m "Hello!"`.
6. If the CLI works, then connect WebUI, gateway, or chat apps.

The active model should normally come from `agents.defaults.modelPreset`, and that name should point to an entry in `modelPresets`. Direct `agents.defaults.provider` and `agents.defaults.model` still work for older configs, but presets are easier to switch and easier to reuse as fallbacks.

## Secret Setup

Environment variables keep API keys out of the config file.

Use the variable name shown by the recipe you picked. The commands below use `OPENROUTER_API_KEY` only as an example; an OpenAI direct recipe uses `OPENAI_API_KEY`, an Anthropic direct recipe uses `ANTHROPIC_API_KEY`, and a custom endpoint can use any variable name you reference in `config.json`.

**macOS / Linux**

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
nanobot agent -m "Hello!"
```

**Windows PowerShell**

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-..."
nanobot agent -m "Hello!"
```

Environment variables set this way apply only to the current terminal. For long-running services such as systemd, Docker, LaunchAgent, or a remote shell, set the variables in that service environment before starting nanobot.

## Recipe: OpenRouter Gateway

This recipe applies when one API key routes many hosted model families.

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
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

Verify:

```bash
nanobot status
nanobot agent -m "Hello!"
```

If this fails with `401` or `unauthorized`, check that `OPENROUTER_API_KEY` is visible in the same terminal or service that starts nanobot. If it fails with `model not found`, choose a model ID that OpenRouter lists for your account.

## Recipe: OpenAI Direct

This recipe applies when you have an OpenAI API key and want to call OpenAI directly instead of through a gateway.

```json
{
  "providers": {
    "openai": {
      "apiKey": "${OPENAI_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "OpenAI",
      "provider": "openai",
      "model": "gpt-5",
      "maxTokens": 4096,
      "contextWindowTokens": 128000,
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

Verify:

```bash
OPENAI_API_KEY="sk-..." nanobot agent -m "Hello!"
```

If your shell cannot use inline environment variables, set `OPENAI_API_KEY` first and then run `nanobot agent -m "Hello!"`. If the provider rejects `apiType`, remove `apiType` unless you are using a documented OpenAI-specific mode.

## Recipe: Anthropic Direct

This recipe applies when your key comes from Anthropic and your model name is an Anthropic model ID, not an OpenRouter model path.

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Anthropic",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
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

Verify:

```bash
ANTHROPIC_API_KEY="sk-ant-..." nanobot agent -m "Hello!"
```

If you copied a model name such as `anthropic/claude-sonnet-4.5`, that is a gateway-style model path and belongs under `provider: "openrouter"`, not `provider: "anthropic"`.

If you use an Anthropic-compatible proxy, keep the preset provider as `anthropic` and set `providers.anthropic.apiBase`:

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
      "label": "Anthropic proxy",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
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

Do not configure Anthropic-compatible endpoints as arbitrary custom provider names; named custom providers use the OpenAI-compatible request format.

## Recipe: Custom OpenAI-Compatible Provider

This recipe applies to an OpenAI-compatible service that is not a named nanobot provider.

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Custom",
      "provider": "custom",
      "model": "provider-model-name",
      "maxTokens": 4096,
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

Verify the endpoint before blaming nanobot:

```bash
curl -sS https://api.example.com/v1/models
nanobot agent -m "Hello!"
```

`apiBase` is the HTTP base URL, not the model name. Include the version path when the service expects it, such as `/v1`. If the service requires a non-empty key but does not validate it, use a placeholder such as `"apiKey": "EMPTY"`.

For multiple custom endpoints, do not overload the single `custom` block. Name each endpoint under `providers` and reference that same name from the preset:

```json
{
  "providers": {
    "workProxy": {
      "apiKey": "${WORK_PROXY_API_KEY}",
      "apiBase": "https://proxy.example.com/v1"
    },
    "lab-local": {
      "apiBase": "http://127.0.0.1:8000/v1"
    }
  },
  "modelPresets": {
    "work": {
      "label": "Work proxy",
      "provider": "workProxy",
      "model": "gpt-4o-mini",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "lab": {
      "label": "Lab local",
      "provider": "lab-local",
      "model": "served-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "work"
    }
  }
}
```

These custom names behave like direct OpenAI-compatible providers: `apiBase` is required, `apiKey` is optional when the endpoint allows anonymous or placeholder credentials, and `apiType` should be left unset. They do not support Anthropic-compatible endpoints; use the `anthropic` provider with `apiBase` for that case.

## Recipe: Ollama Local Model

This recipe applies when Ollama is already installed and the model has been pulled locally.

```bash
ollama serve
ollama pull llama3.2
```

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "modelPresets": {
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

Verify:

```bash
curl -sS http://localhost:11434/v1/models
nanobot agent -m "Hello!"
```

If you see `connection refused`, Ollama is not running or `apiBase` points to the wrong port. If the response is very slow, try a smaller local model or lower `contextWindowTokens`.

## Recipe: vLLM or LM Studio

This recipe applies when a local server exposes an OpenAI-compatible `/v1` API.

```json
{
  "providers": {
    "vllm": {
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "EMPTY"
    }
  },
  "modelPresets": {
    "local": {
      "label": "Local",
      "provider": "vllm",
      "model": "served-model-name",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

For LM Studio, use its local base URL and provider name:

```json
{
  "providers": {
    "lmStudio": {
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "modelPresets": {
    "local": {
      "label": "LM Studio",
      "provider": "lm_studio",
      "model": "local-model",
      "maxTokens": 2048,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "local"
    }
  }
}
```

The config key can be `lmStudio` or `lm_studio`, but the preset provider should use the registry name `lm_studio`.

## Recipe: Fallback Presets

This recipe applies when one provider sometimes rate-limits, one model is expensive, or you want a local backup.

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
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768,
      "temperature": 0.2
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast",
      "fallbackModels": ["deep", "local"]
    }
  }
}
```

`fallbackModels` belongs under `agents.defaults`. String entries are preset names, not raw model names. nanobot tries the active preset first, then the fallback presets in order.

Keep fallback candidates realistic. If the local fallback has a smaller context window, nanobot must build context that fits the smallest window in the active chain.

## Recipe: Langfuse Tracing

This recipe applies after the agent works and you want observability for OpenAI-compatible provider calls.

Install the optional package in the same Python environment that runs nanobot:

```bash
python -m pip install langfuse
```

Set the environment variables before starting nanobot:

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

PowerShell:

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

Langfuse is not a model provider in `config.json`. It is configured through environment variables and traces supported OpenAI-compatible provider calls. Native providers that do not use that client path may not produce Langfuse OpenAI-wrapper traces.

## Recipe: Switch Models at Runtime

Use this after you have more than one preset and are chatting through a supported channel.

```json
{
  "modelPresets": {
    "fast": {
      "label": "Fast",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4.5",
      "maxTokens": 4096,
      "contextWindowTokens": 65536
    },
    "local": {
      "label": "Local",
      "provider": "ollama",
      "model": "llama3.2",
      "maxTokens": 2048,
      "contextWindowTokens": 32768
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "fast"
    }
  }
}
```

In chat:

```text
/model
/model local
/model fast
```

`/model` switching is runtime-only. It does not rewrite `config.json`, and an in-progress turn keeps using the model it started with.

## Quick Failure Map

| Symptom | Usually means | First check |
|---|---|---|
| `401`, `unauthorized`, or `invalid API key` | The key is missing, wrong, expired, or under the wrong provider | Print or re-set the environment variable in the same terminal or service |
| `model not found` | The model ID does not belong to the selected provider or gateway | Compare `modelPresets.<name>.provider` and `modelPresets.<name>.model` |
| `connection refused` | Local server is not running or `apiBase` has the wrong port/path | Run `curl <apiBase>/models` |
| `provider not found` | Provider name is misspelled or uses the config key instead of registry name | Use names such as `openrouter`, `openai`, `anthropic`, `ollama`, `vllm`, `lm_studio` |
| Langfuse shows no traces | Env vars are missing, `langfuse` is not installed in the active Python environment, or the provider path is native | Run `python -m pip show langfuse` and restart nanobot from the same environment |

## Next References

| Need | Read |
|---|---|
| Field meanings and provider resolution | [`providers.md`](./providers.md) |
| Full schema and provider table | [`configuration.md#providers`](./configuration.md#providers) |
| Langfuse details | [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) |
| First-run diagnosis | [`troubleshooting.md`](./troubleshooting.md) |
