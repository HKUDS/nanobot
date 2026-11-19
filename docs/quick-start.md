# Install and Quick Start

Get your first reply from nanobot in a few minutes. Skip chat apps, MCP servers, and deployment until this basic setup works.

If terminals, Python, or API keys are new to you, start with the [beginner walkthrough](./start-without-technical-background.md) instead.

> [!NOTE]
> These docs follow the latest development branch, while the installer below installs the latest stable release. If a screen looks different, check `nanobot --version` and see the [matching release guide](https://nanobot.wiki/docs/latest/getting-started/quick-start).

## What You Need

- Python 3.11 or newer.
- Access to a supported AI provider, company endpoint, or local model server (such as Ollama).
- The API key (or sign-in) and model ID for that service.

Packaged releases include the WebUI and native terminal UI (TUI) for macOS, Linux, and Windows—no Node.js or frontend build tools are needed.

## 1. Install nanobot

The official installer sets up nanobot in its own isolated environment and automatically opens the WebUI on a local desktop.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

You can inspect [`install.sh`](../scripts/install.sh) or [`install.ps1`](../scripts/install.ps1) before running them. If `nanobot` is not on your `PATH` afterward, use the full command printed at the end of the installer output.

## 2. Configure Your Model

When the WebUI opens in your browser, go to **Settings → Models**:

1. Click **New preset** and give it a name (if **Convert to presets** appears, click it first).
2. Open **Provider** and select your provider—or click **Add provider** to enter its API key / sign in.
3. Select a model from the list or enter a model ID available to your account.
4. Click **Save**.

If the browser did not open automatically, run:

```bash
nanobot webui
```

On a headless server or over SSH, use the terminal wizard instead:

```bash
nanobot onboard --wizard
```

By default, nanobot stores its files under `~/.nanobot/`:

| Path | Purpose |
|---|---|
| `~/.nanobot/config.json` | Providers, models, channels, tools, and runtime settings |
| `~/.nanobot/workspace/` | Memory, skills, automations, and generated files |
| `~/.nanobot/sessions/` | Saved conversation history |

## 3. Check the Setup

Verify your local configuration without making a model request:

```bash
nanobot status
```

Confirm that **Config** and **Workspace** show a check mark, your chosen model/preset is listed, and its provider is configured. Unused providers showing `not set` is normal.

## 4. Get the First Reply

In the WebUI (running locally on `http://127.0.0.1:8765`, reachable only from your machine), send:

```text
Hello!
```

Any normal reply confirms that your config, provider, workspace, and WebUI are all working.

### Managing the background gateway

With the official installer, nanobot runs a background gateway so closing the browser or terminal does not stop it. You can manage it anytime:

```bash
nanobot gateway status
nanobot gateway logs
nanobot gateway restart
nanobot gateway stop
```

If you installed nanobot another way (such as `uv` or `pip`), `nanobot webui` stops when you close the terminal unless you start it with `nanobot webui --detach` or `nanobot gateway --background`.

## Terminal-Only Check

To test without a browser, send a single message from the terminal:

```bash
nanobot agent -m "Hello!"
```

Or open an interactive terminal chat:

```bash
nanobot
```

In interactive mode, `Enter` sends and `Shift+Enter` (or `Ctrl+J`) inserts a newline. While nanobot is replying, `Enter` sends immediately, `Tab` queues your message for after the reply, and `Option+Up` (macOS) / `Alt+Up` (Windows/Linux) edits your queued message. Exit with `exit`, `/exit`, `:q`, or `Ctrl+D`.

## Continue with nanobot

Once you have your first reply, you can ask nanobot directly in chat to guide your next setup step. When the built-in `nanobot-document` skill is enabled (under **Skills → Installed**), nanobot reads the documentation bundled with your installation. For example:

- *"I am already using the WebUI. Help me connect Telegram and allow only my account."*
- *"Explain what is shared when I start a new topic or choose a different project."*
- *"My second model preset returns an authentication error. Help me find which setting to check."*

To invoke the documentation skill explicitly:

```text
$nanobot-document Explain how sessions, workspaces, and memory relate in this installation.
```

Or read the guides yourself—add one capability and test it before moving on:

| Goal | Recommended path |
|---|---|
| Learn topics, workspaces, tools, and access modes | [WebUI guide](./webui.md) |
| Connect a chat app | Open **Channels**, then check [Chat Apps](./chat-apps.md) for platform steps |
| Change or add a model | Open **Settings → Models** or browse the [Provider Cookbook](./provider-cookbook.md) |
| Add web search, voice, or image generation | Open **Settings → Capabilities** (see [Configuration](./configuration.md) for advanced options) |
| Add a plugin, CLI App, or MCP server | Open **Apps** or follow [Configure MCP Tools](./guides/configure-mcp-tools.md) |
| Schedule tasks or triggers | Read [Automations](./automations.md) |
| Run continuously or remotely | Read [Deployment](./deployment.md) |
| Integrate from Python | Use the [Python SDK](./python-sdk.md) |

## Other Install Methods

Pick one method below, then continue at [Configure Your Model](#2-configure-your-model).

**uv**

```bash
uv tool install nanobot-ai
nanobot webui
```

**pip (inside a virtual environment)**

```bash
python -m pip install nanobot-ai
nanobot webui
```

If pip reports `externally-managed-environment`, use the official installer, `uv tool install nanobot-ai`, `pipx install nanobot-ai`, or a virtual environment instead of forcing a system-wide install.

**From source (latest `main`)**

Requires Git. nanobot downloads the matching Bun runtime automatically for the TUI; Node.js is not required.

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
python3 -m venv .venv
```

On Windows, use `py -3 -m venv .venv`. Activate the environment (`source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\Activate.ps1` in PowerShell), then run:

```bash
python -m pip install -e .
nanobot webui
```

For contributor details, see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

<details>
<summary>If the <code>nanobot</code> command is not found</summary>

Reuse the full command printed by the official installer, or call Python directly from its dedicated environment:

- **macOS / Linux:** `~/.nanobot/venv/bin/python -I -m nanobot --version`
- **Windows PowerShell:** `& "$HOME\.nanobot\venv\Scripts\python.exe" -I -m nanobot --version`

Replace `--version` with `webui`, `status`, or any other subcommand. For `uv` or `pipx` installs, use the same package manager's environment.

</details>

## Manual Configuration Fallback

<details>
<summary>Manual configuration</summary>

Use this only when the WebUI and terminal wizard are unavailable or you manage `config.json` directly. Run `nanobot onboard` first, then merge a provider and named model preset into `~/.nanobot/config.json`:

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

Keep the provider, endpoint URL, and model ID matched to the same service. See [Provider Cookbook](./provider-cookbook.md) for provider-specific examples and [Configuration](./configuration.md) for all fields.

</details>

## Updating

Open **Settings → About → Update** in the WebUI. Supported installations update and restart in place; others display instructions for their package manager. See [Updating nanobot](./updating.md) for preview releases, backups, and recovery.

For standard Python virtual environments, you can also update from the CLI:

```bash
nanobot update --check
nanobot update
```

## If the First Reply Fails

Change one thing at a time. Start with:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| Symptom | First check |
|---|---|
| `nanobot: command not found` | Reuse the full command printed by the installer (see [Other Install Methods](#other-install-methods)) |
| JSON parse error | Check commas and braces; remember that doc examples are snippets to merge |
| `401` or invalid API key | Confirm the key belongs to the selected provider and has no extra spaces |
| Model not found | Use a model ID available to your account on the selected provider |
| CLI works, but WebUI does not open | Open port `8765`, not the gateway health port `18790` |
| WebUI works, but a chat app does not | Check **Channels** in WebUI, then run `nanobot channels status` |

Continue with [Troubleshooting](./troubleshooting.md) if the cause is still unclear.
