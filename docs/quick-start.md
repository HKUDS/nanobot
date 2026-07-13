# Install and Quick Start

This guide has one goal: get a normal nanobot reply in your browser. Do not add chat apps, MCP servers, fallback models, or deployment until this path works.

If terminals, Python, or API keys are unfamiliar, use the [beginner walkthrough](./start-without-technical-background.md), which explains each term and screen.

These repository docs follow current `main`. The recommended installer uses the stable package, so a newly documented WebUI screen may not appear until the next release. Each advanced guide also provides a CLI or manual config path.

## What You Need

- Python 3.11 or newer.
- Access to one supported AI provider, company endpoint, or local model server.
- The credential, endpoint URL, and model ID required by that service. Local providers such as Ollama may not require a key.

Git is only needed for a source install. The published package already contains the WebUI. A current-source install needs `bun` or `npm` so its WebUI bundle can be built.

## 1. Install nanobot

The recommended installer keeps nanobot out of the system Python environment and opens the setup wizard when installation finishes.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The installer chooses an active virtual environment, `uv`, `pipx`, or a managed environment under `~/.nanobot/venv`. It installs the stable PyPI release unless you explicitly pass `--dev`.

If you prefer to inspect the scripts first, open [`install.sh`](../scripts/install.sh) or [`install.ps1`](../scripts/install.ps1).

## 2. Complete Quick Start

The installer opens `nanobot onboard --wizard`. Choose **Quick Start** and follow the prompts:

1. Choose the provider or endpoint that owns your credential.
2. Enter its API key or base URL when requested.
3. Enter a model ID that the same provider can run.
4. Let Quick Start enable the local WebUI.
5. Set a WebUI password and review the summary.

Quick Start creates or updates:

| Path | Purpose |
|---|---|
| `~/.nanobot/config.json` | Provider, model, WebUI, channel, tool, and runtime settings |
| `~/.nanobot/workspace/` | Sessions, memory, skills, automations, and generated files |

If the installer did not open the wizard, run it yourself:

```bash
nanobot onboard --wizard
```

If you skip the wizard and run `nanobot webui` with no usable model, the launcher offers to run the same Quick Start flow before starting the browser.

## 3. Check the Setup

```bash
nanobot status
```

You want:

- a check mark for **Config** and **Workspace**;
- the model or preset you selected;
- a configured state for the provider used by that model.

Most other providers can say `not set`. This command validates local setup but does not call the model.

## 4. Get the First Reply

```bash
nanobot webui
```

The launcher prepares the local WebSocket channel, starts the gateway, and opens `http://127.0.0.1:8765`. It binds to localhost for the first run, so other devices on your network cannot reach it.

Send:

```text
Hello!
```

Any normal assistant answer is success. It proves that nanobot can load the config, reach the selected model, use the workspace, and serve the browser UI.

Leave the terminal open while using the WebUI. If you prefer a managed background process, stop the foreground process with `Ctrl+C`, then run:

```bash
nanobot webui --background
nanobot gateway status
```

Use `nanobot gateway logs`, `restart`, and `stop` to manage that background gateway.

## Terminal-Only Check

If you do not want the browser or need to isolate a WebUI problem, send one message directly:

```bash
nanobot agent -m "Hello!"
```

Then start an interactive terminal chat with:

```bash
nanobot agent
```

In interactive mode, `Enter` sends and `Alt+Enter` inserts a newline. Exit with `exit`, `/exit`, `:q`, or `Ctrl+D`.

## Choose One Next Step

After the first reply works, add one capability and test again:

| Goal | Recommended path |
|---|---|
| Learn sessions, workspaces, tools, and access modes | [WebUI guide](./webui.md) |
| Connect a chat platform | Open **Settings → Channels**, then use [Chat Apps](./chat-apps.md) for platform prerequisites |
| Change or add a model | Open **Settings → Models**; use the [Provider Cookbook](./provider-cookbook.md) for a recipe |
| Add web search, voice, or image generation | Use the matching WebUI Settings page, then consult [Configuration](./configuration.md) for advanced fields |
| Add an App or MCP integration | Open **Apps** or follow [Configure MCP Tools](./guides/configure-mcp-tools.md) |
| Schedule agent work | Read [Automations](./automations.md) |
| Run continuously or remotely | Read [Deployment](./deployment.md) |
| Integrate from code | Use the [Python SDK](./python-sdk.md) or [OpenAI-Compatible API](./openai-api.md) |

## Other Install Methods

Use one method, then continue at [Complete Quick Start](#2-complete-quick-start).

**uv**

```bash
uv tool install nanobot-ai
nanobot onboard --wizard
```

**pip in a virtual environment**

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

If pip reports `externally-managed-environment`, use the recommended installer, `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or create a virtual environment. Do not force a system-wide install.

**Current source**

`bun` or `npm` must be available. Activate a virtual environment first, then run:

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m pip install .
nanobot onboard --wizard
```

On Windows, if `python -m pip install .` reports that it cannot launch `npm`, run `cd webui`, `npm.cmd install --package-lock=false`, `npm.cmd run build`, and `cd ..` in order, then retry the install.

The source path follows current `main` and can be newer than the published package. A non-editable install triggers the build hook that bundles the current WebUI. For editable Python or frontend development, follow [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and [`../webui/README.md`](../webui/README.md).

If the package is installed but the shell cannot find `nanobot`, use the module form:

```bash
python -m nanobot --version
python -m nanobot onboard --wizard
python -m nanobot webui
```

Some systems name Python `python3` or `py`; use the command that reports Python 3.11 or newer. On Windows, `~` means your user profile directory, such as `C:\Users\you`.

## Manual Configuration Fallback

Use this only when the wizard is unavailable or you intentionally manage JSON. First run `nanobot onboard`, then merge a provider and a named model preset into `~/.nanobot/config.json`.

A generic OpenAI-compatible setup has this shape:

```json
{
  "providers": {
    "custom": {
      "apiKey": "${PROVIDER_API_KEY}",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "provider": "custom",
      "model": "model-id-from-your-provider"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

Replace the provider, endpoint, and model together. Do not pair a credential from one service with a model ID from another. See [Provider Cookbook](./provider-cookbook.md) for hosted, OAuth, company, and local examples, and [Configuration](./configuration.md) for exact fields.

## Updating

Upgrade with the same method you used to install:

```bash
# Recommended installer
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh

# Or one of these
uv tool upgrade nanobot-ai
pipx upgrade nanobot-ai
python -m pip install -U nanobot-ai
```

For a source checkout:

```bash
git pull
python -m pip install .
```

Then check `nanobot --version`. Run `nanobot onboard --refresh` when you want to add newly introduced default fields while preserving existing settings.

## If the First Reply Fails

Do not change several settings at once. Start with:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| Symptom | First check |
|---|---|
| `nanobot: command not found` | Use `python -m nanobot` from the environment where you installed it |
| JSON parse error | Check commas and braces; remember that docs examples are usually snippets |
| `401` or invalid API key | Verify the selected provider owns that key and remove accidental spaces |
| Model not found | Use a model ID available from the provider selected in the active preset |
| CLI works but WebUI does not open | Use port `8765`, not gateway health port `18790` |
| WebUI works but a chat app does not | Check **Settings → Channels**, then run `nanobot channels status` |

Continue with the ordered [Troubleshooting guide](./troubleshooting.md) if the cause is still unclear.
