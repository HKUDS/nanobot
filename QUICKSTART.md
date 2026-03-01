# Scorpion Quick Start

Get up and running in under 2 minutes.

## Prerequisites

- Python 3.11+
- A Google Gemini API key ([get one here](https://aistudio.google.com))

## 1. Install

```bash
git clone https://github.com/Duo-Keyboard-Koalition/scorpion.git
cd scorpion
pip install -e .
```

## 2. Initialize

```bash
scorpion onboard
```

This creates your config file (`~/.scorpion/config.json`) and workspace (`~/.scorpion/workspace/`).

## 3. Configure

Add your Gemini API key to `~/.scorpion/config.json`:

```json
{
  "providers": {
    "gemini": {
      "apiKey": "YOUR_GEMINI_API_KEY"
    }
  }
}
```

That's the only required config. Everything else has sensible defaults:

| Setting | Default |
|---------|---------|
| Model | `gemini-2.5-flash` |
| Max tokens | `8192` |
| Temperature | `0.1` |
| Workspace | `~/.scorpion/workspace` |

## 4. Chat

**Interactive mode:**

```bash
scorpion agent
```

**Single message:**

```bash
scorpion agent -m "What can you do?"
```

**With logs visible:**

```bash
scorpion agent --logs
```

## 5. Connect Chat Platforms (optional)

Connect Scorpion to Telegram, Discord, WhatsApp, and more.

**Example — Telegram:**

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Add to `~/.scorpion/config.json`:

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

3. Start the gateway:

```bash
scorpion gateway
```

See the [README](README.md#-chat-apps) for all supported platforms.

## 6. Built-in Tools

Scorpion comes with these tools out of the box:

| Tool | What it does |
|------|-------------|
| `read_file` | Read files from the workspace |
| `write_file` | Create or overwrite files |
| `edit_file` | Find-and-replace edits |
| `list_dir` | List directory contents |
| `exec_command` | Run shell commands |
| `web_search` | Search the web (requires Brave API key) |
| `web_fetch` | Fetch and extract web page content |
| `send_message` | Send messages to chat channels |
| `spawn_task` | Run background tasks |
| `cron` | Schedule recurring tasks |
| `generate_image` | Generate images with Imagen |
| `generate_video` | Generate videos with Veo |
| `generate_music` | Generate music with Lyria |

## 7. Web Search (optional)

To enable web search, add a [Brave Search API key](https://brave.com/search/api/):

```json
{
  "tools": {
    "braveApiKey": "YOUR_BRAVE_API_KEY"
  }
}
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `scorpion onboard` | Initialize config and workspace |
| `scorpion agent` | Interactive chat |
| `scorpion agent -m "..."` | Single message |
| `scorpion gateway` | Start multi-channel gateway |
| `scorpion status` | Show configuration status |
| `scorpion cron list` | List scheduled tasks |
| `scorpion cron add` | Add a scheduled task |

## File Structure

```
~/.scorpion/
├── config.json              # Configuration
└── workspace/
    ├── AGENTS.md             # Agent behavior instructions
    ├── SOUL.md               # Personality definition
    ├── USER.md               # Info about you
    ├── HEARTBEAT.md          # Periodic tasks
    ├── memory/
    │   └── MEMORY.md         # Long-term memory
    └── skills/               # Custom skills
```

## Next Steps

- Edit `~/.scorpion/workspace/SOUL.md` to customize the agent's personality
- Edit `~/.scorpion/workspace/AGENTS.md` to change agent behavior
- Add MCP servers for external tool integrations (see [README](README.md#mcp-model-context-protocol))
- Set up scheduled tasks with `scorpion cron add`
