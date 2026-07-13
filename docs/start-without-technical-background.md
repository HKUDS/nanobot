# Start Without Technical Background

This walkthrough is for people who have not used a terminal, API key, or JSON
config file before. The goal is only to get one reply in a browser. You do not
need to understand nanobot's architecture or edit its config by hand.

## What You Will Need

- A Windows, macOS, or Linux computer.
- Python 3.11 or newer.
- An account or endpoint that can run an AI model.
- The API key, login, endpoint, and model name required by that service. A
  local model such as Ollama may not require an API key.

An API key is password-like. Do not post it in an issue, screenshot, chat, or
public config file.

## A Few Useful Words

| Word | Meaning |
|---|---|
| Terminal | A text window where you paste a command and press Enter |
| Command | One instruction typed into the terminal |
| Provider | The service or local server that runs the AI model |
| Model ID | The exact model name expected by that provider |
| API key | A secret credential that lets software call the provider |
| Wizard | A question-and-answer setup menu |
| WebUI | The local browser page where you use nanobot |

## 1. Install Python

Download Python from [python.org](https://www.python.org/downloads/) if you do
not already have version 3.11 or newer. On Windows, enable **Add python.exe to
PATH** if the installer shows that option.

Open a terminal:

| System | How |
|---|---|
| Windows | Press `Win`, type `PowerShell`, and open Windows PowerShell |
| macOS | Press `Command+Space`, type `Terminal`, and press Enter |
| Linux | Open your application menu and search for Terminal |

Check Python:

```bash
python --version
```

The result should start with `Python 3.11` or a newer number. If the command is
not found, close and reopen the terminal. You can also try `python3 --version`
on macOS/Linux or `py --version` on Windows.

## 2. Prepare Your Model Details

nanobot does not create an AI provider account for you. Before setup, have these
details nearby:

1. The provider or company endpoint name.
2. Its API key, if it requires one.
3. Its base URL, if its documentation gives you one.
4. A model ID your account can use.

The provider, credential, endpoint, and model must belong together. For example,
an API key from one provider usually cannot call a model name copied from a
different provider.

## 3. Install nanobot

Copy the command for your system, paste it into the terminal, and press Enter.
Copy only the text inside the code block.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The installer downloads the stable nanobot package into an isolated Python
environment and opens the setup wizard. It can take a few minutes on the first
run.

If your organization blocks downloaded install scripts, use the
[alternative install methods](./quick-start.md#other-install-methods) or ask
your administrator to review the scripts first.

## 4. Follow Quick Start

The wizard shows a menu similar to:

```text
> What would you like to do?
  [Q] Quick Start
  [A] Advanced Settings
  [X] Exit
```

Choose **Quick Start**. Use the arrow keys to highlight an option and press
`Enter`.

The wizard asks for only the information needed for the first reply:

1. Choose your provider.
2. Choose an endpoint option if the provider offers several plans.
3. Paste the API key if asked.
4. Enter the base URL if asked.
5. Enter a model ID.
6. Confirm the local WebUI setup.
7. Choose a WebUI password.
8. Review the summary and save.

When you paste a password or API key, the terminal may hide the characters.
That is normal.

If the installer finishes without opening the wizard, run:

```bash
nanobot onboard --wizard
```

If the terminal cannot find `nanobot`, try:

```bash
python -m nanobot onboard --wizard
```

Use `python3` or `py` in place of `python` if that was the command that
worked earlier.

## 5. Open the Browser

Run:

```bash
nanobot webui
```

nanobot starts locally and opens `http://127.0.0.1:8765` in your browser.
Leave the terminal open while you use the WebUI. Enter the WebUI password from
the wizard if the browser asks for it.

Send this message:

```text
Hello!
```

A normal assistant reply means setup is complete. The exact reply does not
matter.

The first-run address is local to your computer. It is not automatically
available to other computers on your network.

## 6. Add One Thing at a Time

Do not configure every feature immediately. Choose one next goal:

| Goal | What to do |
|---|---|
| Change the AI model | Open **Settings → Models** |
| Add a provider credential | Open **Settings → Models**, then find the provider |
| Connect Telegram, Discord, Slack, Feishu, WeChat, or another chat app | Open **Settings → Channels**, choose the platform, and follow its connection steps |
| Add a tool integration | Open **Apps** and choose an App or MCP integration |
| Schedule a reminder or recurring task | Ask nanobot in the target chat, then manage it in **Automations** |
| Work with project files | Start a new chat, choose the project workspace, and review the access setting before sending the task |

Repository docs show the current development version. If your stable package
does not yet show **Settings → Channels**, use the
[Chat Apps guide](./chat-apps.md) or update to a release that includes it.

Some runtime changes ask you to restart nanobot. Use the restart action shown by
the WebUI, or return to the terminal, press `Ctrl+C`, and run
`nanobot webui` again.

For a chat platform's account, bot, token, or permission prerequisites, use the
[Chat Apps guide](./chat-apps.md). For local models and provider-specific
recipes, use the [Provider Cookbook](./provider-cookbook.md).

## If Something Fails

Run these commands one at a time:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| What you see | What it usually means |
|---|---|
| `nanobot: command not found` | Use `python -m nanobot`, `python3 -m nanobot`, or `py -m nanobot` |
| `401`, unauthorized, or invalid API key | The key is wrong, expired, or belongs to a different provider |
| Model not found | The model ID is misspelled or unavailable to your provider account |
| Browser does not open | Open `http://127.0.0.1:8765` yourself and keep the terminal running |
| Browser opens but messages fail | Test `nanobot agent -m "Hello!"` to separate a model problem from a WebUI problem |
| A change was saved but nothing changed | Restart nanobot so the running process reloads the config |

If you ask for help, include your operating system, `nanobot --version`,
`nanobot status`, the exact command, and the exact error. Remove every API key,
bot token, password, OAuth token, and private account ID first.

Continue with the full [Troubleshooting guide](./troubleshooting.md) for an
ordered diagnosis.

## Open nanobot Later

Run:

```bash
nanobot webui
```

Leave that terminal open. To stop nanobot, return to it and press `Ctrl+C`.
Use `nanobot webui --background` only after the normal foreground start works;
then manage it with `nanobot gateway status`, `logs`, `restart`, and
`stop`.
