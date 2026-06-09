# Start Without Technical Background

This page is for you if you have never used a terminal, edited a JSON file, or configured an AI model before.

The goal is small: get one local nanobot reply. Do not connect Telegram, Discord, WebUI, Docker, local models, or deployment yet. Those are easier after the first reply works.

## What You Are Setting Up

You will see these words during setup:

| Word | Plain meaning |
|---|---|
| Terminal | A text window where you paste commands and press Enter. |
| Command | One line of text you run in the terminal. |
| API key | A password-like token from an AI provider. Do not share it publicly. |
| Provider | The service that owns the API key. This guide uses OpenRouter as one example. |
| Model | The AI model ID that the provider can run. |
| Config file | The settings file nanobot reads when it starts. |
| Wizard | An interactive terminal menu that edits the config file for you. |
| Model preset | A named model choice in the config file. |
| `apiBase` | The HTTP address of a provider endpoint. You usually do not need it for OpenRouter. |

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

## 3. Get an OpenRouter API Key

This guide uses OpenRouter as one example provider so every step has concrete names to copy. It is not an endorsement. If you already have another supported provider, use that provider's key and model instead.

1. Open [openrouter.ai/keys](https://openrouter.ai/keys).
2. Create or copy an API key.
3. Keep the key private.

The key usually starts with `sk-or-v1-`. Keep it nearby because the setup wizard will ask you to paste it.

## 4. Install nanobot

The easiest path is the one-command installer. It installs or upgrades nanobot, then starts the setup wizard.

**macOS / Linux**

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)"
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

These commands install the stable PyPI package. To preview what the installer would do without changing your environment, pass `--dry-run`:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)" -- --dry-run
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dry-run
```

Use the development installer only when a maintainer asks you to test the current `main` branch:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh)" -- --dev
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1))) --dev
```

If you prefer to install manually, run:

```bash
python -m pip install nanobot-ai
```

Then check that nanobot is installed:

```bash
nanobot --version
```

If the terminal cannot find `nanobot`, use the module form:

```bash
python -m nanobot --version
```

## 5. Run the Setup Wizard

The one-command installer starts this for you after installation. If you installed manually, run:

```bash
nanobot onboard --wizard
```

If `nanobot` is not found, run:

```bash
python -m nanobot onboard --wizard
```

The wizard is a terminal menu. It is not a graphical app, but it lets you choose options instead of hand-editing every JSON field.

You will see a menu like this:

```text
> What would you like to configure?
  [P] LLM Provider
  [M] Model Presets
  [C] Chat Channel
  [H] Channel Common
  [A] Agent Settings
  [I] API Server
  [G] Gateway
  [T] Tools
  [V] View Configuration Summary
  [S] Save and Exit
  [X] Exit Without Saving
```

For the first setup, only use these choices:

1. Choose `[P] LLM Provider`.
2. Select OpenRouter.
3. Paste your OpenRouter API key.
4. Leave `apiBase` empty unless OpenRouter or your deployment guide explicitly tells you to set one.
5. Return to the main menu.
6. Choose `[M] Model Presets`.
7. Add or edit a preset named `primary`.
8. Set:

```text
label: Primary
provider: openrouter
model: anthropic/claude-sonnet-4-5
maxTokens: 4096
contextWindowTokens: 65536
temperature: 0.1
```

If OpenRouter says your account cannot use that model, use another OpenRouter model ID that your account can access.

Then choose `[S] Save and Exit`.

The wizard creates or updates:

| Path | Meaning |
|---|---|
| `~/.nanobot/config.json` | Settings file. |
| `~/.nanobot/workspace/` | Working folder for memory, sessions, and generated files. |

## 6. Manual Config Fallback

Use this only if the wizard is unavailable or you prefer opening the file yourself.

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
    "openrouter": {
      "apiKey": "sk-or-v1-your-key-here"
    }
  },
  "modelPresets": {
    "primary": {
      "label": "Primary",
      "provider": "openrouter",
      "model": "anthropic/claude-sonnet-4-5",
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

Replace `sk-or-v1-your-key-here` with your real OpenRouter key.

If OpenRouter says your account cannot use that model, replace the `model` value with a model ID from OpenRouter that your account can access.

Save the file.

## 7. Send the First Message

Run:

```bash
nanobot agent -m "Hello!"
```

If that works, nanobot is installed and can call the model.

You should see a normal assistant reply in the terminal. The exact words will differ, but it should look like this shape:

```text
Hello! How can I help you today?
```

If `nanobot` is not found, run:

```bash
python -m nanobot agent -m "Hello!"
```

## 8. If Something Fails

Do not change many things at once. Check the exact error:

| Error or symptom | What it usually means |
|---|---|
| `JSON parse error` | The config file has a missing comma, extra comma, or mismatched brace. Copy the example again. |
| `401`, `unauthorized`, or `invalid API key` | The API key is wrong, expired, has extra spaces, or was pasted under the wrong provider. |
| `model not found` | The model ID is not available through OpenRouter or your account cannot use it. |
| `nanobot: command not found` | The install worked in Python, but your shell cannot find the script. Use `python -m nanobot ...`. |
| No response after editing config | Restart the command. Long-running processes read config when they start. |

For a fuller diagnosis path, see [`troubleshooting.md`](./troubleshooting.md).

## What Not to Configure Yet

Skip these until the first local message works:

- `apiBase`: OpenRouter already has a default endpoint. You only need `apiBase` for local models, proxies, custom OpenAI-compatible providers, or special regional/subscription endpoints.
- WebUI and chat apps: first prove `nanobot agent -m "Hello!"`.
- fallback models: useful later, but not needed for the first reply.
- Langfuse: useful for observability, but not needed for first setup.

## Next Steps

After the first reply works:

| Goal | Read |
|---|---|
| Understand the normal quick start | [`quick-start.md`](./quick-start.md) |
| Open the browser UI | [`../webui/README.md`](../webui/README.md) |
| Connect chat apps | [`chat-apps.md`](./chat-apps.md) |
| Choose another provider or local model | [`providers.md`](./providers.md) |
| Understand config fields | [`configuration.md`](./configuration.md) |
