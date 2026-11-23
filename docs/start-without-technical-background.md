# Start Without Technical Background

This walkthrough is for people who have not used a terminal, API key, or config file before. The goal is simple: get your first reply from nanobot in a web browser. You do not need to edit any code or config files by hand.

## What You Will Need

- A Windows, macOS, or Linux computer.
- Python 3.11 or newer.
- An AI model service (such as OpenRouter, OpenAI, Anthropic, or a local model like Ollama) and its login or API key.

> [!CAUTION]
> Treat an API key like a password. Never paste it into screenshots, chats, or public support requests.

## A Few Useful Words

| Word | What it means |
|---|---|
| Terminal | A text window where you paste a command and press Enter |
| Command | One line of instructions you run in the terminal |
| Provider | The AI service (or local app like Ollama) that runs the model |
| Model ID | The exact model name your provider expects |
| API key | A secret key that lets nanobot connect to your provider |
| WebUI | The browser page where you chat with and configure nanobot |

## 1. Install Python

If you do not already have Python 3.11 or newer, download it from [python.org](https://www.python.org/downloads/). On Windows, check the box labeled **Add python.exe to PATH** during installation so your terminal can find Python automatically.

Open your terminal:

| System | How to open |
|---|---|
| Windows | Press `Win`, type `PowerShell`, and open **Windows PowerShell** |
| macOS | Press `Command+Space`, type `Terminal`, and press Enter |
| Linux | Open your app menu and search for **Terminal** |

Type this command and press Enter:

```bash
python --version
```

You should see something like `Python 3.12.x` (any version `3.11` or higher works). If you get an error saying `python` is not recognized, close and reopen the terminal, or try `python3 --version` (macOS/Linux) or `py --version` (Windows).

## 2. Prepare Your Model Details

Having a regular chat website subscription (like ChatGPT Plus or Claude Pro) does not automatically give you API access. Before continuing, make sure you have an AI provider ready.

If you do not have a provider yet, [OpenRouter](https://openrouter.ai/) is a simple starting point (any supported provider works):

1. Create an account at [OpenRouter](https://openrouter.ai/).
2. Open [API Keys](https://openrouter.ai/settings/keys) and create a key. Keep it somewhere private for Step 4.
3. Pick a model from the [model catalog](https://openrouter.ai/models) and copy its model ID. Pick a model that supports tools (often labeled **Tools**) if you want nanobot to read files or run actions for you.

If you prefer a model that runs locally on your own computer with no API key, see the [Ollama recipe](./provider-cookbook.md#recipe-ollama-local-model). If you are using a company-managed AI service, ask your administrator for the endpoint URL, key, and model ID.

Whatever provider you choose, make sure the **provider, key, and model ID all belong to the same service**.

## 3. Install nanobot

Copy the command for your system, paste it into the terminal, and press Enter:

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | sh
```

**Windows PowerShell**

```powershell
irm https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.ps1 | iex
```

The installer sets up nanobot in its own dedicated folder and automatically opens the WebUI in your browser when finished. This first setup can take a few minutes.

> [!TIP]
> If your terminal says `nanobot` is not found later, reuse the full command printed at the end of the installer output. If your network or company blocks downloaded install scripts, see [Other Install Methods](./quick-start.md#other-install-methods).

## 4. Configure Your Model in the WebUI

Once the WebUI opens in your browser, go to **Settings → Models**:

1. Click **New preset** and give it a name (if you see **Convert to presets**, click that first).
2. Open **Provider** and choose your provider. To add a new one, choose **Add provider**, enter your API key (or complete sign-in), and save.
3. Pick a model from the list or paste your model ID.
4. Click **Save**.

If the browser did not open automatically after installation, run:

```bash
nanobot webui
```

On a server without a browser (such as over SSH), the installer opens a terminal setup wizard instead—choose **Quick Start** and follow the prompts.

## 5. Get the First Reply

If your browser still did not open automatically, copy the **entire login link** printed in the terminal (including the `#...` part at the end) and paste it into your browser's address bar. Keep that link private because it signs your browser in.

Type this in the chat box and send it:

```text
Hello!
```

Any normal reply means nanobot is set up and working. By default, nanobot only runs locally on your computer and cannot be reached by other devices on your network.

## 6. Add One Thing at a Time

Now that nanobot replies, you can ask it in chat to guide you through your next goal—for example: *"I am using the WebUI. Help me connect Telegram and allow only my account."*

You can also explore one feature at a time in the WebUI:

| What you want to do | Where to go |
|---|---|
| Change your AI model or add a provider | **Settings → Models** |
| Connect Telegram, Discord, Slack, Feishu, WeChat, or another chat app | **Channels** (see [Chat Apps](./chat-apps.md) for platform steps) |
| Add tools, plugins, or MCP integrations | **Apps** |
| Set a reminder or recurring task | Ask nanobot in chat, then manage it in **Automations** |
| Work with files on your computer | Try [Your first file task](#your-first-file-task) below |

If a setting asks you to restart nanobot, click the **Restart** button shown in the WebUI (or run `nanobot gateway restart` in the terminal).

## Your First File Task

1. Create a practice folder (for example `Documents/nanobot-practice`) and copy a short text file into it so your originals stay safe.
2. Start a new topic in the WebUI, click the folder selector, pick that practice folder, and click **Confirm**. Leave access set to **Restricted** (this keeps nanobot safely inside your chosen folder so it cannot touch files elsewhere on your computer).
3. Send: *"Read notes.txt and write a short summary to summary.md in this folder."* (Replace `notes.txt` with your file's name.)

Open your practice folder—you should see a new `summary.md` file there.

> [!NOTE]
> Choosing a workspace folder sets where nanobot reads and writes files. Attaching a file only shares that file with the chat. Also, starting a new topic or choosing a different folder does not separate long-term memory—if you need completely separate memory (for example, for different clients), see [Multiple Instances](./multiple-instances.md).

## Open nanobot Later

Whenever you want to open the WebUI again, run:

```bash
nanobot webui
```

With the official installer, nanobot stays running in the background even after you close the browser or terminal. You can check or stop it anytime with `nanobot gateway status`, `nanobot gateway restart`, or `nanobot gateway stop`.

## If Something Fails

Run these commands one by one to narrow down the issue:

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

| What you see | What to check |
|---|---|
| `nanobot: command not found` | Reuse the full command printed by the installer |
| `401`, unauthorized, or invalid API key | Check that the key is complete, active, and belongs to the selected provider |
| Model not found | Double-check the spelling of the model ID and confirm your account can use it |
| Browser does not open | Copy the complete login link from the terminal (including everything after `#`) |
| Browser opens, but messages fail | Run `nanobot agent -m "Hello!"` to check whether the problem is the model or the browser |
| Saved a setting, but nothing changed | Restart nanobot so the new setting takes effect |

If you ask for help, share your operating system, `nanobot --version`, `nanobot status`, and the exact error—with all API keys, tokens, and passwords removed. For step-by-step diagnosis, see [Troubleshooting](./troubleshooting.md).
