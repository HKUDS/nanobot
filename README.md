<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Self-Hosted Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

## What is nanobot?

Nanobot is a self-hosted AI assistant that connects to your chat apps — Telegram, Discord, Slack, WhatsApp, and Email — and runs entirely on your own machine. It works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, or a local model), so you keep full control over your data and costs. Nanobot remembers context across conversations through its persistent memory system and can take actions using built-in tools like file operations, web search, shell commands, and a plugin skill system. The core framework is around 4,000 lines of async Python with a bus-based architecture — no microservices, no containers, just a single process.

<div align="center">
  <img src="nanobot_arch.png" alt="Architecture" width="800">
</div>

## Install

The PyPI package is **`nanobot-ai`**. After installation, the CLI command is **`nanobot`**.

### Option 1: uv (recommended)

```bash
uv tool install nanobot-ai
```

### Option 2: pip

```bash
pip install nanobot-ai
```

### Option 3: From source

```bash
git clone https://github.com/cgajagon/nanobot.git
cd nanobot
make install
```

### Optional extras

Install extras with bracket syntax, e.g. `pip install nanobot-ai[oauth]` or `uv tool install nanobot-ai[oauth,pptx]`.

| Extra | Description |
|-------|-------------|
| `oauth` | OAuth login for OpenAI Codex and GitHub Copilot |
| `pptx` | PowerPoint file tools |
| `prometheus` | Prometheus metrics export |

## Quick Start

Get nanobot running in 2 minutes.

**1. Run the onboarding wizard:**

```bash
nanobot onboard
```

This creates the config directory at `~/.nanobot/` and walks you through initial setup.

**2. Edit `~/.nanobot/config.json`:**

At minimum, you need an LLM provider. Here is an example using OpenRouter:

```json
{
  "llm": {
    "provider": "openrouter",
    "apiKey": "sk-or-v1-YOUR_API_KEY",
    "model": "anthropic/claude-sonnet-4-20250514"
  }
}
```

**3. Test with a single-shot message:**

```bash
nanobot agent -m "Hello!"
```

**4. Enter interactive mode:**

```bash
nanobot agent
```

This starts a REPL session where you can have a back-and-forth conversation. Exit with `Ctrl+D`, `exit`, or `/quit`.

## Chat Apps

Nanobot connects to multiple chat platforms simultaneously via `nanobot gateway`. Each channel is configured in the `channels` section of `~/.nanobot/config.json`.

| Channel | What you need |
|---------|---------------|
| **Telegram** | Bot token from @BotFather |
| **Discord** | Bot token + Message Content intent |
| **WhatsApp** | QR code scan (requires Node.js >=18) |
| **Slack** | Bot token + App-Level token |
| **Email** | IMAP/SMTP credentials |

Start all enabled channels:

```bash
nanobot gateway
```

---

<details>
<summary><b>Telegram</b> (Recommended)</summary>

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot. Copy the bot token.

2. Get your Telegram user ID (message [@userinfobot](https://t.me/userinfobot) to find it).

3. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

4. Start the gateway:

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and create a new application. Add a Bot under the Bot tab.

2. Under the Bot tab, enable **MESSAGE CONTENT INTENT**.

3. Get your Discord user ID: enable Developer Mode in Discord settings, then right-click your avatar and select **Copy User ID**.

4. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

5. Invite the bot to your server: go to **OAuth2 > URL Generator**, select the `bot` scope, then grant **Send Messages** and **Read Message History** permissions. Open the generated URL to invite.

6. Start the gateway:

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b> (requires Node.js >=18)</summary>

1. Log in by scanning the QR code:

```bash
nanobot channels login
```

2. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

3. Run two terminals — one for the WhatsApp bridge, one for the gateway:

```bash
# Terminal 1
nanobot channels login

# Terminal 2
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b> (Socket Mode — no public URL needed)</summary>

1. Create a new app at [api.slack.com/apps](https://api.slack.com/apps).

2. Enable **Socket Mode** and generate an **App-Level Token** with the `connections:write` scope.

3. Add the following **OAuth scopes** under OAuth & Permissions: `chat:write`, `reactions:write`, `app_mentions:read`.

4. Subscribe to these **events** under Event Subscriptions: `message.im`, `message.channels`, `app_mention`.

5. Go to **App Home** and enable the **Messages Tab** with "Allow users to send Slash commands and messages from the messages tab".

6. **Install to Workspace** and copy the Bot User OAuth Token (`xoxb-...`).

7. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

8. Start the gateway:

```bash
nanobot gateway
```

> [!TIP]
> `groupPolicy` controls how the bot responds in channels: `"mention"` (default, responds when @mentioned), `"open"` (responds to all messages), or `"allowlist"` (responds to listed users). DMs default to open; disable with `"dm": {"enabled": false}`.

</details>

<details>
<summary><b>Email</b> (IMAP/SMTP)</summary>

1. Get your IMAP/SMTP credentials. For Gmail, use a dedicated account with an [App Password](https://support.google.com/accounts/answer/185833).

2. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-nanobot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

`consentGranted` must be set to `true` for the channel to start. If `allowFrom` is empty, all senders are accepted. The default TLS/SSL settings are correct for Gmail. Set `autoReplyEnabled` to `false` to disable automatic replies.

3. Start the gateway:

```bash
nanobot gateway
```

</details>
