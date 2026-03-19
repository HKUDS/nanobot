# Quick Start

Complete nanobot setup in 5 minutes and have your first conversation with your AI assistant.

---

## Step 1: Install nanobot

=== "uv (Recommended)"

    ```bash
    uv tool install nanobot-ai
    ```

=== "pip"

    ```bash
    pip install nanobot-ai
    ```

Verify installation succeeded:

```bash
nanobot --version
```

!!! tip "Haven't installed uv yet?"
    Please see the [Installation Guide](installation.md) to install uv and nanobot first.

---

## Step 2: Run the onboarding wizard

```bash
nanobot onboard
```

The wizard guides you through initial setup and creates the following files in `~/.nanobot/`:

```
~/.nanobot/
├── config.json          # Main config file
└── workspace/
    ├── AGENTS.md        # Agent behavior guidelines
    ├── USER.md          # User profile
    ├── SOUL.md          # Agent personality definition
    ├── TOOLS.md         # Tool usage preferences
    └── HEARTBEAT.md     # Periodic task settings
```

!!! note "Already have configuration?"
    Running `nanobot onboard` again does not overwrite existing settings; it only fills missing parts.

---

## Step 3: Configure API key and model

Open `~/.nanobot/config.json` and add your LLM API key and model configuration.

```bash
# Open with any editor
vim ~/.nanobot/config.json
# or
nano ~/.nanobot/config.json
# or
code ~/.nanobot/config.json
```

### Configure API key

Using [OpenRouter](https://openrouter.ai/keys) (recommended for global users) as an example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  }
}
```

Other common providers:

=== "Anthropic (Claude)"

    ```json
    {
      "providers": {
        "anthropic": {
          "apiKey": "sk-ant-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "OpenAI (GPT)"

    ```json
    {
      "providers": {
        "openai": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "DeepSeek"

    ```json
    {
      "providers": {
        "deepseek": {
          "apiKey": "sk-xxxxxxxxxxxx"
        }
      }
    }
    ```

=== "Ollama (Local)"

    ```json
    {
      "providers": {
        "ollama": {
          "apiBase": "http://localhost:11434"
        }
      },
      "agents": {
        "defaults": {
          "provider": "ollama",
          "model": "llama3.2"
        }
      }
    }
    ```

### Configure model (optional)

You can optionally specify a default model. If omitted, nanobot auto-detects based on configured API keys:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "openrouter"
    }
  }
}
```

### Minimal complete configuration example

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

!!! warning "Protect your API key"
    `config.json` contains sensitive API keys. Do not commit this file to version control (git).

---

## Step 4: Chat in CLI

After setup, start chatting immediately:

```bash
nanobot agent
```

You will see the interactive interface:

```
nanobot> Hello! What can you help me with?
```

nanobot supports multiple usage modes:

```bash
# Interactive chat (default)
nanobot agent

# One-off message (non-interactive)
nanobot agent -m "What's the weather today?"

# Show plain-text responses (do not render Markdown)
nanobot agent --no-markdown

# Show runtime logs
nanobot agent --logs
```

To exit interactive mode: type `exit`, `quit`, or press `Ctrl+D`.

!!! tip "Congratulations!"
    You have completed the basic setup successfully. The next steps explain how to connect nanobot to Telegram so you can chat with your AI assistant from your phone anytime.

---

## Step 5: Connect Telegram (Optional)

Telegram is the easiest chat platform to set up and is recommended for beginners.

### Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Enter a Bot name (display name, e.g., `My Nanobot`)
4. Enter a Bot username (must end with `bot`, e.g., `my_nanobot_bot`)
5. BotFather returns a **Bot Token**, similar to: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

### Get your Telegram User ID

Your User ID appears in Telegram settings as `@yourUserId`.
Remove the `@` symbol when copying.

Or send any message to your bot and check nanobot runtime logs, where the sender User ID is shown.

### Update config file

Merge the following into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
      "allowFrom": ["your_telegram_user_id"]
    }
  }
}
```

| Field | Description |
|------|------|
| `token` | Bot Token from @BotFather |
| `allowFrom` | List of User IDs allowed to interact with the bot (empty means deny all) |

!!! warning "Security reminder"
    The `allowFrom` list controls who can use your bot.
    Use `["*"]` to allow everyone, but use with caution to avoid API quota abuse.

---

## Step 6: Start Gateway

```bash
nanobot gateway
```

After Gateway starts, you will see output similar to:

```
[nanobot] Gateway starting on port 18790
[nanobot] Telegram channel connected
[nanobot] Ready to receive messages
```

Now open Telegram and send a message to your bot.

!!! note "Difference between Gateway and CLI"
    - `nanobot agent`: local CLI interactive mode, direct terminal chat
    - `nanobot gateway`: starts server mode and continuously listens to chat platform messages

---

## Full Configuration Example

Here is a minimal complete config including Telegram:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxxxxxxxxxxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    }
  }
}
```

---

## Next Steps

- **Learn the onboarding wizard**: [Onboarding Wizard Details](onboarding.md)
- **Connect other chat platforms**: [Channel Setup Guide](../channels/index.md)
- **Configure more LLM providers**: [Providers Docs](../providers/index.md)
- **Explore tools and skills**: [Tools and Skills](../tools-skills/index.md)