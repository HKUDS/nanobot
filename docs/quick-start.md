# Install and Quick Start

This page gets one local nanobot reply working. After that, you can add the WebUI, chat apps, local models, web search, MCP, deployment, or custom plugins.

If you have never used a terminal or edited a config file before, use [`start-without-technical-background.md`](./start-without-technical-background.md) first. This page assumes you are comfortable pasting commands and editing JSON snippets.

## Before You Start

You need:

- Python 3.11 or newer.
- One LLM provider you can call. OpenRouter is a simple first choice for global users because one key can route many model families.
- Git only if you install from source.
- Node.js or Bun only if you are developing the WebUI itself.

> [!IMPORTANT]
> Repository docs may describe features that are available first in source.
> Install from PyPI or `uv` for the stable day-to-day release; install from
> source when you want the newest repository behavior or plan to contribute.

## 1. Install

Pick one install method.

**One-command setup:**

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)"
```

On Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The default command installs or upgrades `nanobot-ai` from PyPI, then starts `nanobot onboard --wizard`.

To preview the plan without changing your environment, pass `--dry-run`; combine it with `--dev` when you want to preview the main-branch install.

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)" -- --dry-run
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dry-run
```

To install the current `main` branch instead, pass `--dev`:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)" -- --dev
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dev
```

If you prefer to inspect the script first, open [`../scripts/install.sh`](../scripts/install.sh) or [`../scripts/install.ps1`](../scripts/install.ps1).

**Stable release with `uv`:**

```bash
uv tool install nanobot-ai
nanobot --version
```

**Stable release with pip:**

```bash
python -m pip install nanobot-ai
nanobot --version
```

**Latest source checkout:**

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install -e .
nanobot --version
```

If your shell cannot find `nanobot` after a pip install, run the module form:

```bash
python -m nanobot --version
python -m nanobot onboard
```

On Windows, `~` in the docs means your user profile directory, for example `C:\Users\you`.

## 2. Initialize

```bash
nanobot onboard
```

Use the wizard if you prefer prompts instead of editing JSON by hand:

```bash
nanobot onboard --wizard
```

Initialization creates:

| Path | What it is |
|------|------------|
| `~/.nanobot/config.json` | Main settings file for providers, models, channels, tools, gateway, and API |
| `~/.nanobot/workspace/` | Agent workspace for memory, sessions, heartbeat tasks, skills, and artifacts |

If you already have a config, `nanobot onboard` can refresh missing default fields without overwriting your existing values.

## 3. Configure a Provider

Open `~/.nanobot/config.json`. Add or merge these blocks into the file created by `nanobot onboard`; do not replace the whole file unless you want to reset the config.

**API key:**

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

**Model preset:**

```json
{
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-5",
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

The provider and model inside a preset should match. An OpenRouter key should be used with `"provider": "openrouter"` and a model ID OpenRouter can serve. Direct `agents.defaults.provider` and `agents.defaults.model` still work for existing configs, but named presets are the recommended path because they also power `/model` switching and fallback chains. For Anthropic direct, OpenAI direct, Ollama, vLLM, Bedrock, gateway providers, OAuth providers, and local models, see [`providers.md`](./providers.md).

**What about `apiBase` / base URL?**

`apiBase` is the HTTP base URL of the provider endpoint, not the model name. Most hosted providers in nanobot already know their default endpoint, so you usually only set `apiKey` and a model preset. Set `apiBase` when you are using:

- `custom` for a third-party or self-hosted OpenAI-compatible API;
- a local OpenAI-compatible server such as Ollama, vLLM, or LM Studio;
- a provider-specific alternate endpoint, regional endpoint, proxy, or subscription endpoint.

Examples:

```json
{
  "providers": {
    "custom": {
      "apiKey": "${CUSTOM_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  }
}
```

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434/v1"
    }
  }
}
```

If the provider's docs say the endpoint is `/v1`, include `/v1` in `apiBase`. The model ID still belongs in the active `modelPresets` entry.

If you prefer not to store secrets in `config.json`, reference an environment variable and set it before starting nanobot:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  }
}
```

## 4. Test One Message

Run a one-shot CLI message:

```bash
nanobot agent -m "Hello!"
```

A successful first run proves that:

- the `nanobot` command is installed;
- `~/.nanobot/config.json` can be loaded;
- the selected provider and model can answer;
- the default workspace can be created and used.

If that works, start an interactive CLI chat:

```bash
nanobot agent
```

Exit interactive mode with `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

## 5. Choose Your Next Step

| Want to... | Go to |
|---|---|
| Understand config, workspace, gateway, channels, memory, and tools | [`concepts.md`](./concepts.md) |
| Copy another provider or local model setup | [`provider-cookbook.md`](./provider-cookbook.md) |
| Understand provider/model matching | [`providers.md`](./providers.md) |
| Open the bundled browser UI | [`../webui/README.md`](../webui/README.md) |
| Connect Telegram, Discord, WeChat, Slack, Email, or another chat app | [`chat-apps.md`](./chat-apps.md) |
| Configure web search, MCP, security, memory, gateway, or runtime settings | [`configuration.md`](./configuration.md) |
| Run with Docker, systemd, or LaunchAgent | [`deployment.md`](./deployment.md) |
| Debug a failure | [`troubleshooting.md`](./troubleshooting.md) |

## Updating

**pip:**

```bash
python -m pip install -U nanobot-ai
nanobot --version
```

**uv:**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

**Source checkout:**

```bash
git pull
python -m pip install -e .
nanobot --version
```

If you use WhatsApp, rebuild the local bridge after upgrading:

```bash
rm -rf ~/.nanobot/bridge
nanobot channels login whatsapp
```

## First-Run Troubleshooting

| Symptom | What to check |
|---------|---------------|
| `nanobot: command not found` | Use `python -m nanobot ...`, or add your Python scripts directory to `PATH`. |
| `ModuleNotFoundError: nanobot` | Confirm you installed into the same Python environment that is running the command. |
| JSON parse errors | Check commas and braces in `~/.nanobot/config.json`; examples above are partial snippets to merge. |
| Authentication or 401 errors | Check that the API key is valid, copied without spaces, and placed under the provider you selected. |
| Provider/model errors | Make sure the active preset uses the provider that owns your API key and that the model exists there. |
| The CLI works but a chat app does not reply | First keep `nanobot gateway` running, then follow [`chat-apps.md`](./chat-apps.md). |
| WebUI does not open | Enable the WebSocket channel and open port `8765`, not the gateway health port `18790`. |

For a fuller diagnosis flow, see [`troubleshooting.md`](./troubleshooting.md).
