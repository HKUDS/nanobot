# Install and Quick Start

This guide has one goal: get a normal nanobot reply in your browser. Do not add chat apps, MCP servers, fallback models, or deployment until this path works.

If terminals, Python, or API keys are unfamiliar, use the [beginner walkthrough](./start-without-technical-background.md), which explains each term and screen.

These repository docs follow current `main`. The recommended installer uses the stable package, so a newly documented WebUI screen may not appear until the next release. Each advanced guide also provides a CLI or manual config path.

## What You Need

- Python 3.11 or newer.
- Access to one supported AI provider, company endpoint, or local model server.
- The credential, endpoint URL, and model ID required by that service. Local providers such as Ollama may not require a key.

Git and [Bun](https://bun.sh/) are only needed for a source install. The published package already contains the WebUI and fetches a checksummed, version-matched TUI archive with its licenses, notices, corresponding application source, source offer, and relinking instructions on first use.

## 1. Install nanobot

The recommended installer keeps nanobot out of the system Python environment. On a fresh local desktop, it starts the WebUI when installation finishes.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The installer chooses an active virtual environment, `uv`, `pipx`, or a managed environment under `~/.nanobot/venv`. It installs the stable PyPI release. At the end it prints the exact command it used to run nanobot; if `nanobot` is not on `PATH`, reuse that full command in the examples below.

If you prefer to inspect the scripts first, open [`install.sh`](../scripts/install.sh) or [`install.ps1`](../scripts/install.ps1).

## 2. Configure Your Model

Keep the installer terminal open. The browser opens the local WebUI; go to **Settings → Models** and:

1. Choose the provider or endpoint that owns your credential.
2. Enter its API key or base URL when required.
3. Create or select a model preset using a model ID that provider can run.
4. Save the configuration.

The WebUI launcher creates or updates:

| Path | Purpose |
|---|---|
| `~/.nanobot/config.json` | Provider, model, WebUI, channel, tool, and runtime settings |
| `~/.nanobot/workspace/` | Memory, skills, automations, and generated files |
| `~/.nanobot/sessions/<workspace-id>/` | Recent session history stored outside the workspace; the ID remains stable across workspace moves |

If the installer did not open the browser, run:

```bash
nanobot webui
```

SSH, headless, and existing-config installs can open the same complete configuration editor used
by `nanobot agent`:

```bash
nanobot onboard --wizard
```

The first page contains the workspace and active model essentials. Open a section or press `/` to
find any advanced provider, channel, tool, API, MCP, memory, or runtime setting. Changes are staged
until you press `Ctrl+S`.

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

If the installer-started WebUI is no longer running, run `nanobot webui` again. Leave that launcher open; the first-run WebUI is bound to localhost, so other devices on your network cannot reach it.

Send:

```text
Hello!
```

Any normal assistant answer is success. It proves that nanobot can load the config, reach the selected model, use the workspace, and serve the browser UI.

Interactive WebUI and TUI launchers share one on-demand gateway. Closing one launcher leaves it running for the others; closing the last launcher stops it. If you prefer a persistent background process, press `Ctrl+C`, then run:

```bash
nanobot gateway --background
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

In interactive mode, `Enter` sends and `Shift+Enter` inserts a newline (`Ctrl+J` is the
universal fallback). While a turn is running,
`Enter` steers it, `Tab` queues a follow-up, and `Option+Up` on macOS (`Alt+Up` on
Windows/Linux) edits the latest queued message. Exit
with `exit`, `/exit`, `:q`, or `Ctrl+D`.

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

Use one method, then continue at [Configure Your Model](#2-configure-your-model).

**uv**

```bash
uv tool install nanobot-ai
nanobot webui
```

**pip in a virtual environment**

```bash
python -m pip install nanobot-ai
nanobot webui
```

If pip reports `externally-managed-environment`, use the recommended installer, `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or create a virtual environment. Do not force a system-wide install.

**Current source**

Clone the repository and install it in editable mode. Bun is required so the checkout can run
its matching native TUI instead of mixing current Python with an older release binary.

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux or
`.venv\Scripts\Activate.ps1` in Windows PowerShell, then run:

```bash
python -m pip install -e .
nanobot webui
```

The source path follows current `main` and can be newer than the published package. The editable
install keeps Python pointed at the checkout; `nanobot agent` runs `tui/` with Bun, and
`nanobot webui` automatically rebuilds `webui/` when its bundled assets are stale. All normal
commands remain the same as a stable install. For development details, follow
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).

If the package is installed but the shell cannot find `nanobot`, use the runner that owns the installation. The recommended installer prints the exact command to reuse. Common forms are:

```bash
uv tool run --from nanobot-ai nanobot --version
pipx run --spec nanobot-ai nanobot --version
~/.nanobot/venv/bin/python -m nanobot --version
```

On Windows, the managed-environment form is `& "$HOME\.nanobot\venv\Scripts\python.exe" -m nanobot --version`. Replace `--version` with `webui`, `onboard --wizard`, or any other arguments you need. Use plain `python -m nanobot` only when that Python executable belongs to the environment where nanobot was installed.

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
git pull --ff-only
python -m pip install -e .
```

Because the install is editable, normal source changes are visible immediately. Re-running the
install synchronizes any changed Python dependencies; the TUI and WebUI refresh their own
dependencies/assets when launched. Then check `nanobot --version`. Run
`nanobot onboard --refresh` when you want to add newly introduced default fields while preserving
existing settings.

## If the First Reply Fails

Do not change several settings at once. Start with:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| Symptom | First check |
|---|---|
| `nanobot: command not found` | Reuse the installer command or method-specific runner described under [Other Install Methods](#other-install-methods) |
| JSON parse error | Check commas and braces; remember that docs examples are usually snippets |
| `401` or invalid API key | Verify the selected provider owns that key and remove accidental spaces |
| Model not found | Use a model ID available from the provider selected in the active preset |
| CLI works but WebUI does not open | Use port `8765`, not gateway health port `18790` |
| WebUI works but a chat app does not | Check **Settings → Channels**, then run `nanobot channels status` |

Continue with the ordered [Troubleshooting guide](./troubleshooting.md) if the cause is still unclear.
