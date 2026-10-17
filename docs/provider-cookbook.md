# Provider Cookbook

This page is for cases where you already know what you want to connect and need a pasteable setup. Each recipe shows what to set, what to run, and what a failure usually means.

If this is your first install and terminal commands are new to you, start with [`start-without-technical-background.md`](./start-without-technical-background.md). If you want the field-by-field explanation, read [`providers.md`](./providers.md) and then [`configuration.md#providers`](./configuration.md#providers).

Use **Settings → Models** for the recipes below. The collapsed **Manual configuration** examples are snippets for headless deployments or configuration managed as code. Keep existing config sections when merging a snippet, and keep real credentials on your own machine.

Recipes are examples, not rankings. Pick the recipe that matches the credential, endpoint, and model ID you already intend to use.

## Choose a Recipe

Match the recipe to the credential or endpoint you already have:

| What you have | Recipe | Must match |
|---|---|---|
| A gateway key and model IDs that include a model family path, such as `provider/model-name` | [OpenRouter Gateway](#recipe-openrouter-gateway) | API key, provider config key, preset provider, and gateway model ID |
| An OpenCode Zen or Go key | [OpenCode Zen or Go](#recipe-opencode-zen-or-go) | `OPENCODE_API_KEY`, the Zen/Go provider key, and a model ID from the matching OpenCode endpoint |
| An OpenAI platform API key and OpenAI model ID | [OpenAI Direct](#recipe-openai-direct) | `OPENAI_API_KEY`, `provider: "openai"`, and an OpenAI model available to that account |
| An Anthropic API key and Anthropic model ID | [Anthropic Direct](#recipe-anthropic-direct) | `ANTHROPIC_API_KEY`, `provider: "anthropic"`, and a non-gateway model ID |
| A Kimi Coding Plan key | [Kimi Coding Plan](#recipe-kimi-coding-plan) | `KIMI_CODING_API_KEY`, `provider: "kimi_coding"`, and `model: "kimi-for-coding"` |
| An OpenAI-compatible `/v1` endpoint that is not a named nanobot provider | [Custom OpenAI-Compatible Provider](#recipe-custom-openai-compatible-provider) | `apiBase`, optional API key, and the model ID served by that endpoint |
| Ollama already running locally | [Ollama Local Model](#recipe-ollama-local-model) | Ollama `apiBase`, pulled model name, and local server availability |
| vLLM, LM Studio, or another local OpenAI-compatible server | [vLLM or LM Studio](#recipe-vllm-or-lm-studio) | Local `/v1` base URL, any required key, and served model name |
| A primary model plus one or more backups | [Fallback Presets](#recipe-fallback-presets) | Named presets in `modelPresets`, referenced from `agents.defaults.fallbackModels` |
| A working agent and a Langfuse project | [Langfuse Tracing](#recipe-langfuse-tracing) | Langfuse env vars in the same process environment that starts nanobot |

## How to Use a Recipe

1. Install nanobot and open `nanobot webui`.
2. Open **Settings → Models → New preset**. If **Convert to presets** appears, choose it first.
3. Select the recipe's provider from **Provider**, or choose **Add provider** and save its credentials and endpoint.
4. Select a model available to your account. Expand **Advanced options** if you need generation settings or an explicit request API.
5. Save the preset and select it in the chat composer.
6. Send `Hello!` and confirm a normal reply before connecting a chat app.

For fallback recipes, create each preset first, then use **Enable preset** and arrange the order in **Settings → Models**. The first enabled preset is the primary; the others are fallbacks.

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

Select OpenRouter in **Settings → Models → New preset**, add its API key through **Provider → Add provider** if needed, and choose a model available to your account. Save and select the preset in chat.

This recipe applies when one API key routes many hosted model families.

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

</details>

Verify:

```bash
nanobot status
nanobot agent -m "Hello!"
```

If this fails with `401` or `unauthorized`, check that `OPENROUTER_API_KEY` is visible in the same terminal or service that starts nanobot. If it fails with `model not found`, choose a model ID that OpenRouter lists for your account.

## Recipe: OpenCode Zen or Go

In **Settings → Models → New preset**, choose OpenCode Zen or OpenCode Go to match your account, add its credential, select a model from that endpoint, and save. Select the preset in chat.

This recipe applies when your credential comes from OpenCode Zen or OpenCode Go. Both providers use `OPENCODE_API_KEY`; pick the provider block that matches the subscription or balance you want to use.

OpenCode Zen:

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

</details>

OpenCode Go:

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

</details>

Verify:

```bash
nanobot status
nanobot agent -m "Hello!"
```

OpenCode's docs list models across multiple endpoint types. The `opencode_zen` and `opencode_go` providers in nanobot use the OpenAI-compatible `chat/completions` path. If a model fails with `model not found` or an endpoint shape error, choose a model that OpenCode lists under `chat/completions` for the matching Zen or Go endpoint.

## Recipe: OpenAI Direct

In **Settings → Models → New preset**, select OpenAI, add its API key, choose a model available to your account, and save. Leave request API selection on Auto unless your endpoint requires an explicit choice.

This recipe applies when you have an OpenAI API key and want to call OpenAI directly instead of through a gateway.

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

</details>

Verify:

```bash
OPENAI_API_KEY="sk-..." nanobot agent -m "Hello!"
```

If your shell cannot use inline environment variables, set `OPENAI_API_KEY` first and then run `nanobot agent -m "Hello!"`. Leave API selection on Auto unless you need a specific API in the preset's **Advanced options**; see [preset API settings](./configuration.md#preset-request-api). If your configuration still uses `apiType`, follow the [migration instructions](./configuration.md#legacy-openai-api-selector-migration).

## Recipe: Anthropic Direct

In **Settings → Models → New preset**, select Anthropic, add its API key, choose a Claude model available to your account, and save. Select the preset in chat.

This recipe applies when your key comes from Anthropic and your model name is an Anthropic model ID, not an OpenRouter model path.

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

</details>

Verify:

```bash
ANTHROPIC_API_KEY="sk-ant-..." nanobot agent -m "Hello!"
```

If you copied a model name such as `anthropic/claude-sonnet-4.5`, that is a gateway-style model path and belongs under `provider: "openrouter"`, not `provider: "anthropic"`.

If you use an Anthropic-compatible proxy, keep the preset provider as `anthropic` and set `providers.anthropic.apiBase`:

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

</details>

Do not configure Anthropic-compatible endpoints as arbitrary custom provider names; named custom providers use the OpenAI-compatible request format.

## Recipe: Kimi Coding Plan

In **Settings → Models → New preset**, select Kimi Coding, add your Coding Plan key, choose `kimi-for-coding`, and save. Select the preset in chat.

This recipe applies when your key comes from Kimi's Coding Plan endpoint. Nanobot uses a dedicated `kimi_coding` provider for this Anthropic Messages API endpoint; do not configure it as a generic `custom` provider.

<details>
<summary>Manual configuration</summary>

```json
{
  "providers": {
    "kimiCoding": {
      "apiKey": "${KIMI_CODING_API_KEY}"
    }
  },
  "modelPresets": {
    "kimiCoding": {
      "provider": "kimi_coding",
      "model": "kimi-for-coding",
      "maxTokens": 4096,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "kimiCoding"
    }
  }
}
```

</details>

Verify:

```bash
nanobot status
nanobot agent -m "Hello!"
```

The default base URL is `https://api.kimi.com/coding/v1`. This endpoint requires a Claude-compatible `User-Agent`; nanobot sends `claude-code/0.1.0` by default. If your account requires a different value, override it with `providers.kimiCoding.extraHeaders.User-Agent`.

## Recipe: Custom OpenAI-Compatible Provider

In **Settings → Models → New preset → Provider → Add provider**, create a custom connection with the endpoint URL and any required key. Select its served model, save the preset, and select it in chat.

This recipe applies to an OpenAI-compatible service that is not a named nanobot provider.

<details>
<summary>Manual configuration</summary>

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

</details>

Verify the endpoint before blaming nanobot:

```bash
curl -sS https://api.example.com/v1/models
nanobot agent -m "Hello!"
```

`apiBase` is the HTTP base URL, not the model name. Include the version path when the service expects it, such as `/v1`. If the service requires a non-empty key but does not validate it, use a placeholder such as `"apiKey": "EMPTY"`.

For multiple custom endpoints, do not overload the single `custom` block. Name each endpoint under `providers` and reference that same name from the preset:

<details>
<summary>Manual configuration</summary>

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
      "provider": "workProxy",
      "model": "gpt-4o-mini",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    },
    "lab": {
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

</details>

These custom names define direct connections: `apiBase` is required and `apiKey` is optional when the endpoint allows anonymous or placeholder credentials. Declare accepted protocols and a default with [`providers.<name>.api`](./configuration.md#custom-connection-apis). An Anthropic-compatible endpoint uses `supportedApis: ["anthropic_messages"]`; model presets can select any protocol within the connection declaration.

## Recipe: Ollama Local Model

Follow the server preparation below, then open **Settings → Models → New preset**, select or add an Ollama connection at `http://localhost:11434/v1`, choose the downloaded model, and save. Select the preset in chat. If nanobot runs in a container or on another computer, `localhost` refers to that host; use an address reachable from nanobot.

If Ollama is not installed, follow its [official quickstart](https://docs.ollama.com/quickstart) ([Linux setup](https://docs.ollama.com/linux)). Keep the Ollama app or service running. If no service is running, start `ollama serve` in a terminal and leave it open; do not start a second server when the app or system service already owns the port. In a separate terminal, download a model and confirm it is listed:

```bash
ollama pull llama3.2
ollama list
```

Use that exact model name in nanobot. Downloading requires internet access and disk space; model inference then runs on the machine hosting Ollama.

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
    "local": {
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

</details>

Verify:

```bash
curl -sS http://localhost:11434/v1/models
```

Send `Hello!` in the WebUI with the local preset selected. A CLI test uses its own session/default selection; to make the local preset the global primary, enable it and move it first in **Settings → Models**.

Local inference does not disable network tools. For local-only document work, turn off **Web access**, avoid cloud fallbacks and remote integrations, and review shell access. Shell commands can still use the network even with a sandbox; a strict offline policy needs host/container network controls. See [local tool security](./guides/secure-local-ai-agent.md).

If you see `connection refused`, Ollama is not running or `apiBase` points to the wrong port. If every response is slow, try a smaller local model or lower `contextWindowTokens`.

If direct Ollama responses are fast but tool-using nanobot turns repeatedly evaluate thousands of prompt tokens, the model's chat template may be moving its tool definitions between requests. See [Improve Ollama Tool-Calling Prompt Cache Reuse](./guides/configure-ollama-prompt-cache.md) for a diagnostic procedure and an optional model-specific workaround.

## Recipe: vLLM or LM Studio

Start your local model server, then use **Settings → Models → New preset** to add its connection with the local `/v1` endpoint and any required key. Enter the served model name, save, and select the preset in chat.

This recipe applies when a local server exposes an OpenAI-compatible `/v1` API.

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
    "local": {
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

</details>

For LM Studio, use its local base URL and provider name:

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
    "local": {
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

</details>

The config key can be `lmStudio` or `lm_studio`, but the preset provider should use the registry name `lm_studio`.

## Recipe: Fallback Presets

Create each preset in **Settings → Models**, use **Enable preset**, and arrange the primary first with backups after it. Test each preset in chat before relying on the fallback order.

This recipe applies when one provider sometimes rate-limits, one model is expensive, or you want a local backup.

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
      "model": "claude-sonnet-4-5",
      "maxTokens": 4096,
      "contextWindowTokens": 200000,
      "temperature": 0.1
    },
    "local": {
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

</details>

`fallbackModels` belongs under `agents.defaults`. String entries are preset names, not raw model names. nanobot tries the active preset first, then the fallback presets in order.

Keep fallback candidates realistic. If the local fallback has a smaller context window, nanobot must build context that fits the smallest window in the active chain.

## Recipe: Langfuse Tracing

This recipe applies after the agent works and you want observability for OpenAI-compatible provider calls, or for the Codex OAuth provider.

Install the optional package in the same Python environment that runs nanobot:

```bash
nanobot plugins enable langfuse
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

Langfuse is not a model provider in `config.json`. It is configured through environment variables and traces supported OpenAI-compatible provider calls, plus Codex OAuth provider calls via Langfuse's native SDK. Other native providers that do not use either path may not produce Langfuse traces.

## Recipe: Switch Models at Runtime

Use this after you have more than one preset and are chatting through a supported channel.

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
    },
    "local": {
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

</details>

In chat:

```text
/model
/model local
/model fast
```

`/model` stores the selection in the current session without rewriting `config.json`. The selection survives restarts, does not affect other sessions, and an in-progress turn keeps using the model it started with.

## Quick Failure Map

| Symptom | Usually means | First check |
|---|---|---|
| `401`, `unauthorized`, or `invalid API key` | The key is missing, wrong, expired, or under the wrong provider | Print or re-set the environment variable in the same terminal or service |
| `model not found` | The model ID does not belong to the selected provider or gateway | Compare `modelPresets.<name>.provider` and `modelPresets.<name>.model` |
| `connection refused` | Local server is not running or `apiBase` has the wrong port/path | Run `curl <apiBase>/models` |
| `provider not found` | Provider name is misspelled or uses the config key instead of registry name | Use names such as `openrouter`, `openai`, `anthropic`, `ollama`, `vllm`, `lm_studio` |
| Langfuse shows no traces | Env vars are missing, `langfuse` is not installed in the active Python environment, or the provider path is a native provider other than Codex OAuth | Run `python -m pip show langfuse` and restart nanobot from the same environment |

## Next References

| Need | Read |
|---|---|
| Field meanings and provider resolution | [`providers.md`](./providers.md) |
| Full schema and provider table | [`configuration.md#providers`](./configuration.md#providers) |
| Langfuse details | [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) |
| First-run diagnosis | [`troubleshooting.md`](./troubleshooting.md) |
