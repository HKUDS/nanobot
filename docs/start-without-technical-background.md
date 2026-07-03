# Start Without Technical Background

This page is for you if you have never used a terminal, edited a JSON file, or configured an AI model before.

The goal is small: get one local nanobot reply in your browser. Do not connect Telegram, Discord, Docker, local models, or deployment yet. Those are easier after the first reply works.

## What You Are Setting Up

You only need these words for Quick Start:

| Word | Plain meaning |
|---|---|
| Terminal | A text window where you paste commands and press Enter. |
| Command | One line of text you run in the terminal. |
| API key | A password-like token from an AI provider. Do not share it publicly. |
| Config file | The settings file nanobot reads when it starts. |
| Wizard | An interactive terminal menu that edits the config file for you. |
| Browser UI | The local web page where you chat with nanobot. |

## 1. Open a Terminal

You will paste commands into a terminal. Copy only the command text inside each code block; do not copy the ``` marks.

| System | How to open it |
|---|---|
| Windows | Press `Win`, type `PowerShell`, then open **Windows PowerShell**. |
| macOS | Press `Command` + `Space`, type `Terminal`, then press `Enter`. |
| Linux | Open your app launcher, search for `Terminal`, then open it. |

When the terminal opens, click inside it, paste the command, and press `Enter`. If a command prints text and returns to a prompt, that is usually normal.

## 2. Install Python

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/).

On Windows, enable **Add python.exe to PATH** during installation if the installer shows that option.

In that terminal, check Python:

```bash
python --version
```

If Windows says `python` is not found, close and reopen PowerShell. If it still does not work, try:

```bash
py --version
```

If `py` works but `python` does not, replace `python` with `py` in the commands below.

If macOS or Linux says `python` is not found, try:

```bash
python3 --version
```

If `python3` works but `python` does not, replace `python` with `python3` in the manual commands below. The one-command installer already checks both `python3` and `python`.

## 3. Get a Provider API Key

nanobot does not create AI accounts or API keys for you. Use an AI provider account, company endpoint, subscription endpoint, or local model server that you already control. If the provider has an OpenAI-compatible base URL in its docs, keep that nearby too.

For the setup path:

1. Open your provider's API key page.
2. Create or copy an API key.
3. Keep the key private.
4. Keep the provider's base URL nearby if the provider docs show one.

## 4. Install nanobot

The easiest path is the one-command installer. It installs or upgrades nanobot, then starts the setup wizard. On macOS and Linux it avoids system-wide pip installs by using an active virtual environment, `uv`, `pipx`, or a managed venv under `~/.nanobot/venv`.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

These commands install the stable PyPI package. To preview what the installer would do without changing your environment, pass `--dry-run`:

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh -s -- --dry-run
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dry-run
```

Use the development installer only when a maintainer asks you to test the current `main` branch:

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh -s -- --dev
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dev
```

If the command says `curl` or `irm` is not found, or it cannot download from GitHub, use one of the manual install commands below.

If `uv` is installed, use:

```bash
uv tool install nanobot-ai
```

If you prefer pip, use it only inside an environment you control:

```bash
python -m pip install nanobot-ai
```

If pip reports `externally-managed-environment` on macOS or Linux, go back to the one-command installer, use `uv tool install nanobot-ai`, use `pipx install nanobot-ai`, or create a virtual environment first.

Then check that nanobot is installed:

```bash
nanobot --version
```

If the terminal cannot find `nanobot`, use the module form:

```bash
python -m nanobot --version
```

Use `python3 -m nanobot --version` or `py -m nanobot --version` if that is the Python command that worked in step 2.

## 5. Run the Setup Wizard

The one-command installer starts this for you after installation. If you installed manually, run:

```bash
nanobot onboard --wizard
```

If `nanobot` is not found, run:

```bash
python -m nanobot onboard --wizard
```

Use `python3 -m nanobot onboard --wizard` or `py -m nanobot onboard --wizard` if that is the Python command that worked in step 2.

The wizard is a terminal menu. It is not a graphical app, but it lets you choose options instead of hand-editing every JSON field.

You will see a menu like this:

```text
> What would you like to do?
  [Q] Quick Start
  [A] Advanced Settings
  [X] Exit
```

Move through the wizard like this:

| When you see | Do this |
|---|---|
| A menu | Use the arrow keys to highlight an option, then press `Enter`. |
| The provider menu | Choose the company or service you want to use. |
| An endpoint menu | Choose the standard API or subscription plan endpoint that matches your key. |
| An API key field | Paste the key, then press `Enter`. |
| A provider base URL field | Paste the provider base URL from its docs, then press `Enter`. |
| The Model ID field | Paste a model name from your provider, then press `Enter`. |
| A back option in Advanced Settings | Choose it to return to the previous menu. |

For the first setup, choose `[Q] Quick Start`. It configures the recommended local browser UI and default AI settings for you. Use `Advanced Settings` later only if you need a chat app, a tool setup, or provider-specific fields.

1. Choose `[Q] Quick Start`.
2. Choose the provider you want to use.
3. Choose the endpoint if the wizard asks, such as Standard API, Coding Plan, Token Plan, or Step Plan.
4. Paste your API key if the wizard asks for one.
5. Paste the provider base URL if the wizard asks for one.
6. Paste a model ID that provider can run.
7. Confirm that Quick Start should configure the local WebUI.
8. Set the WebUI password when prompted.
9. Review the Quick Start summary. The wizard saves and exits when Quick Start finishes.

The recommended path configures the local WebUI, requires a WebUI password, and writes default AI settings. You do not need to choose a separate chat app for the first run.

If you already know that you need custom headers, provider-specific request fields, a chat app, or tools, choose `Advanced Settings` instead. [`provider-cookbook.md`](./provider-cookbook.md) has copyable examples for several common provider setups. After you change advanced settings, a save option appears in the main menu. Choose `[S] Save and Exit`.

The wizard creates or updates:

| Path | Meaning |
|---|---|
| `~/.nanobot/config.json` | Settings file. |
| `~/.nanobot/workspace/` | Working folder for memory, sessions, and generated files. |

If Quick Start finished successfully, skip to [Open the WebUI](#7-open-the-webui). The next two sections are only for manual setup.

## Manual Setup: How to Merge JSON Snippets

Most docs examples are snippets, not whole files. Your `config.json` has one outer `{ ... }`. Add new top-level sections such as `providers`, `modelPresets`, `agents`, or `channels` inside that same outer object.

Do not paste two separate JSON objects into one file:

```text
{
  "providers": { "...": "..." }
}
{
  "channels": { "...": "..." }
}
```

Merge them into one object:

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "channels": {
    "websocket": {
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true
    }
  }
}
```

Notice the comma after the `providers` block. JSON needs commas between sibling sections, but not after the last section. If this feels hard, use `nanobot onboard --wizard` whenever possible.

## 6. Manual Setup: Config Fallback

Use this only if the wizard is unavailable or you prefer opening the file yourself.

Run `nanobot onboard` first if `~/.nanobot/config.json` does not exist yet.

Use one of these commands:

**Windows PowerShell**

```powershell
notepad "$env:USERPROFILE\.nanobot\config.json"
```

**macOS**

```bash
open -e ~/.nanobot/config.json
```

**Linux**

```bash
xdg-open ~/.nanobot/config.json
```

If this is a brand-new install and you have not configured anything else yet, replace the file with this minimal config:

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.example.com/v1"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "custom",
      "model": "model-id-from-your-provider",
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "temperature": 0.1
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  },
  "channels": {
    "websocket": {
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true
    }
  }
}
```

Replace `your-api-key`, `https://api.example.com/v1`, `model-id-from-your-provider`, and `your-webui-password` with your own values.

For copyable provider-specific examples, use [`provider-cookbook.md`](./provider-cookbook.md).

Save the file.

## 7. Open the WebUI

First check that nanobot can read the saved setup:

```bash
nanobot status
```

This should show the config file path, workspace path, and the active model or preset. If `nanobot` is not found, use `python -m nanobot status`, `python3 -m nanobot status`, or `py -m nanobot status`, matching the Python command that worked in step 2.

It is normal for most providers to say `not set`. Only the provider you selected for the active preset needs to look configured.

Start the local browser UI:

```bash
nanobot webui
```

This starts nanobot and opens `http://127.0.0.1:8765` in your browser. Leave the terminal open while you use the WebUI. Enter the WebUI password you set in the wizard if the browser asks for one.

Send this first message in the browser:

```text
Hello!
```

If that works, nanobot is installed and can call the model. You should see a normal assistant reply in the browser. The exact words will differ, but it should look like this shape:

```text
Hello! How can I help you today?
```

If `nanobot` is not found, run:

```bash
python -m nanobot webui
```

Use `python3 -m nanobot webui` or `py -m nanobot webui` if that is the Python command that worked in step 2.

Once this works, nanobot can help with its own next setup step. In the browser UI, ask it to read these docs and update your current config for one specific goal, then run `/restart` when nanobot tells you the config is ready. For example, ask it to add one provider preset or configure one chat app.

## 8. If Something Fails

Do not change many things at once. Check the exact error:

| Error or symptom | What it usually means |
|---|---|
| `JSON parse error` | The config file has a missing comma, extra comma, or mismatched brace. Copy the example again. |
| `401`, `unauthorized`, or `invalid API key` | The API key is wrong, expired, has extra spaces, or was pasted under the wrong provider. |
| `model not found` | Your account cannot use the default model. Return to `nanobot onboard --wizard`, choose `Advanced Settings`, then edit `Model Presets`. |
| `nanobot: command not found` | The install worked in Python, but your shell cannot find the script. Use `python -m nanobot ...`, `python3 -m nanobot ...`, or `py -m nanobot ...`, matching the Python command that worked earlier. |
| No response after editing config | Restart the command. Long-running processes read config when they start. |

For a fuller diagnosis path, see [`troubleshooting.md`](./troubleshooting.md).

## What Not to Configure Yet

Skip these until the first local message works:

- `apiBase`: hosted built-in providers often already have default endpoints. You only need `apiBase` for local models, proxies, custom OpenAI-compatible providers, or special regional/subscription endpoints.
- chat apps: first prove the local browser UI can answer.
- fallback models: useful later, but not needed for the first reply.
- Langfuse: useful for observability, but not needed for first setup.

## Next Steps

After the first reply works, choose only one next goal. Keep the terminal that runs `nanobot webui` open whenever you use the WebUI. Chat apps use the same gateway service underneath.

### Open the Browser UI Again

Run:

```bash
nanobot webui
```

Leave that terminal open; the browser should open automatically.

To stop the WebUI later, return to the gateway terminal and press `Ctrl+C`.

If `nanobot` is not found, run `python -m nanobot webui`, `python3 -m nanobot webui`, or `py -m nanobot webui`, matching the Python command that worked earlier. More details are in [`webui.md`](./webui.md).

### Connect a Chat App

1. Read the section for one app in [`chat-apps.md`](./chat-apps.md).
2. Add only that app's config snippet. Merge it into the existing file instead of replacing the whole file.
3. Run:

```bash
nanobot channels status
nanobot gateway
```

4. Leave the gateway terminal open, then send a message from the allowed account.

Start with a private chat or a test server. Do not set `allowFrom` to `["*"]` unless you intentionally want anyone who can reach that channel to talk to the bot.

### Change Models or Add Backups

Use [`providers.md`](./providers.md) when a provider/model pair fails, and [`provider-cookbook.md`](./provider-cookbook.md) when you want copyable snippets. Keep model choices in `modelPresets`, then select the active one with `agents.defaults.modelPreset`.

### Ask for Help

When you ask for help, include:

- your operating system;
- the command you ran;
- `nanobot --version`;
- `nanobot status`;
- whether the browser UI can answer `Hello!`;
- the exact error text;
- a config snippet with API keys and tokens removed.

Never paste real API keys, bot tokens, OAuth tokens, or private chat IDs into a public issue or chat.

If you find a docs mistake, outdated command, or confusing step, please open an issue: <https://github.com/HKUDS/nanobot/issues>.
