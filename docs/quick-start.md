# Install and Quick Start

## Install

> [!IMPORTANT]
> These docs may describe features that are available first in the latest source code.
> If you want the newest features and experiments, install from source.
> If you want the most stable day-to-day experience, install from PyPI or with `uv`.

Pick **one** install method:

Prerequisites:

- Python 3.11 or newer
- Git, only if you install from source
- `uv`, only if you choose the `uv` install method
- No Node.js or Bun required unless you are developing the WebUI itself

**Install from source** (latest features, experimental changes may land here first; recommended for development)

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install -e .
```

**Install with [uv](https://github.com/astral-sh/uv)** (stable release, fast)

```bash
uv tool install nanobot-ai
```

**Install from PyPI** (stable release)

```bash
python -m pip install nanobot-ai
```

Verify the command is available:

```bash
nanobot --version
```

If your shell cannot find `nanobot` after a `pip` install, try:

```bash
python -m nanobot --version
python -m nanobot onboard
```

### Update to latest version

**PyPI / pip**

```bash
python -m pip install -U nanobot-ai
nanobot --version
```

**uv**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

**Using WhatsApp?** Rebuild the local bridge after upgrading:

```bash
rm -rf ~/.nanobot/bridge
nanobot channels login whatsapp
```

## Quick Start

> [!TIP]
> Set your API key in `~/.nanobot/config.json`.
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (Global)
>
> For other LLM providers, please see [`configuration.md`](./configuration.md).
>
> For web search capability setup, please see the web-search section in [`configuration.md`](./configuration.md#web-search).

**1. Initialize**

```bash
nanobot onboard
```

Use `nanobot onboard --wizard` if you want the interactive setup wizard.

This creates:

| Path | What it is |
|------|------------|
| `~/.nanobot/config.json` | Main settings file for providers, model, channels, and tools |
| `~/.nanobot/workspace/` | Working directory for memory, sessions, heartbeat tasks, skills, and artifacts |

On Windows, `~` means your user profile directory, for example
`C:\Users\you\.nanobot`.

**2. Configure** (`~/.nanobot/config.json`)

Configure these **two parts** in your config (other options have defaults). Add
or merge these blocks into the existing file created by `nanobot onboard`; do
not replace the whole file unless you know you want to reset it.

*Set your API key* (e.g. OpenRouter, recommended for global users):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Set your model* (optionally pin a provider):
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

The provider and model should match. For example, an OpenRouter key should be
used with `"provider": "openrouter"` and an OpenRouter model ID. For local
models or other providers, see [`configuration.md`](./configuration.md).

If you prefer not to store secrets in `config.json`, you can reference an
environment variable instead. Set the environment variable before starting
nanobot:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}"
    }
  }
}
```

**3. Test one message**

```bash
nanobot agent -m "Hello!"
```

If that works, start an interactive chat:

```bash
nanobot agent
```

Type `exit`, `quit`, `/exit`, `/quit`, `:q`, or press `Ctrl+D` to leave
interactive mode.

## First-Run Troubleshooting

| Symptom | What to check |
|---------|---------------|
| `nanobot: command not found` | Use `python -m nanobot ...`, or make sure your Python scripts directory is on `PATH`. |
| Authentication or 401 errors | Check that the API key is valid, copied without spaces, and placed under the provider you selected. |
| Provider/model errors | Make sure `agents.defaults.provider` matches the provider that owns your API key, and that the model name exists for that provider. |
| JSON parse errors | Check commas and braces in `~/.nanobot/config.json`. The examples above are partial blocks to merge into the existing file. |
| Nothing happens in chat apps | First verify `nanobot agent -m "Hello!"` works locally, then configure channels in [`chat-apps.md`](./chat-apps.md). |
