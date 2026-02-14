# Nanobot Agent Guide

This file contains everything an AI agent needs to know to configure, run, and troubleshoot nanobot.

## Overview

Nanobot is an ultra-lightweight personal AI assistant (~4,000 lines of core code). It connects to LLM providers (OpenRouter, Anthropic, OpenAI, etc.) and exposes a chat interface via CLI, HTTP gateway, or messaging channels (Telegram, WhatsApp, Discord, Slack, Email, etc.).

## Project Structure

```
nanobot/
├── agent/              # Core agent logic (loop, context, memory, skills, subagent, tools)
├── bus/                # Message routing
├── channels/           # Chat channel integrations (telegram, whatsapp, discord, slack, email, etc.)
├── cli/                # CLI commands
├── config/             # Configuration schema and loader
│   ├── schema.py       # Pydantic models — the source of truth for all config fields
│   └── loader.py       # JSON loading with camelCase <-> snake_case conversion
├── cron/               # Scheduled tasks
├── heartbeat/          # Proactive wake-up
├── providers/          # LLM providers and voice transcription
│   ├── registry.py     # Provider registry — single source of truth for provider metadata
│   └── transcription.py # Groq Whisper voice transcription
├── session/            # Conversation sessions
├── skills/             # Bundled skills (github, weather, tmux, summarize, memory, cron, skill-creator)
└── utils/              # Helper utilities
bridge/                 # WhatsApp bridge (Node.js/TypeScript)
compose.yml             # Docker Compose configuration
Dockerfile              # Container build definition
pyproject.toml          # Python package definition
.env.example            # Environment variable template
```

## Configuration

### Config File Location

- **Host**: `~/.nanobot/config.json`
- **Docker container**: `/home/nanobot/.nanobot/config.json` (mounted from host via volume)

The config file uses **camelCase** keys. The loader (`config/loader.py`) automatically converts them to snake_case for the Pydantic schema. When writing config, always use camelCase.

### Full Config Schema

The authoritative schema is defined in `nanobot/config/schema.py`. Here is the complete structure with all fields and defaults:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20,
      "memoryWindow": 50
    }
  },
  "providers": {
    "openrouter": { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "anthropic":  { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "openai":     { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "deepseek":   { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "groq":       { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "gemini":     { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "zhipu":      { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "dashscope":  { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "moonshot":   { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "minimax":    { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "aihubmix":   { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "vllm":       { "apiKey": "", "apiBase": null, "extraHeaders": null },
    "custom":     { "apiKey": "", "apiBase": null, "extraHeaders": null }
  },
  "channels": {
    "whatsapp":  { "enabled": false, "bridgeUrl": "ws://localhost:3001", "bridgeToken": "", "allowFrom": [] },
    "telegram":  { "enabled": false, "token": "", "allowFrom": [], "proxy": null },
    "discord":   { "enabled": false, "token": "", "allowFrom": [], "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json", "intents": 37377 },
    "feishu":    { "enabled": false, "appId": "", "appSecret": "", "encryptKey": "", "verificationToken": "", "allowFrom": [] },
    "dingtalk":  { "enabled": false, "clientId": "", "clientSecret": "", "allowFrom": [] },
    "mochat":    { "enabled": false, "baseUrl": "https://mochat.io", "socketUrl": "", "socketPath": "/socket.io", "clawToken": "", "agentUserId": "", "sessions": [], "panels": [], "allowFrom": [] },
    "slack":     { "enabled": false, "mode": "socket", "webhookPath": "/slack/events", "botToken": "", "appToken": "", "userTokenReadOnly": true, "groupPolicy": "mention", "groupAllowFrom": [], "dm": { "enabled": true, "policy": "open", "allowFrom": [] } },
    "email":     { "enabled": false, "consentGranted": false, "imapHost": "", "imapPort": 993, "imapUsername": "", "imapPassword": "", "imapMailbox": "INBOX", "imapUseSsl": true, "smtpHost": "", "smtpPort": 587, "smtpUsername": "", "smtpPassword": "", "smtpUseTls": true, "smtpUseSsl": false, "fromAddress": "", "autoReplyEnabled": true, "pollIntervalSeconds": 30, "markSeen": true, "maxBodyChars": 12000, "subjectPrefix": "Re: ", "allowFrom": [] },
    "qq":        { "enabled": false, "appId": "", "secret": "", "allowFrom": [] }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60
    },
    "restrictToWorkspace": false
  }
}
```

### Key Configuration Rules

1. **At least one provider with a non-empty `apiKey` is required** or nanobot will refuse to start with "No API key configured".
2. **Provider matching**: The model name is matched against provider keywords. For example, a model containing "openai" or "gpt" matches the `openai` provider. Gateway providers (like `openrouter`) can route any model.
3. **OpenRouter is the recommended gateway** for access to all models via a single API key. Keys start with `sk-or-`.
4. **Only include providers you use** -- omitted providers default to empty (disabled). You do not need to list all providers.
5. **`allowFrom` on channels**: Empty array `[]` means allow everyone. To restrict, add user IDs/phone numbers.
6. **`tools.restrictToWorkspace`**: Set to `true` for production to sandbox the agent to the workspace directory only.
7. **`tools.web.search.apiKey`**: Brave Search API key. Without it, web search is disabled.
8. **`agents.defaults.workspace`**: Must be a path that exists and is writable. When running in Docker, use `~/.nanobot/workspace` (the default) since it resolves inside the container. Do NOT use host-specific absolute paths like `/mnt/apps/...` as they don't exist inside the container.

### Environment Variables

Config can also be set via environment variables. Nanobot uses Pydantic Settings with:
- **Prefix**: `NANOBOT_`
- **Nested delimiter**: `__`

Examples:
```bash
NANOBOT_GATEWAY__HOST=0.0.0.0
NANOBOT_GATEWAY__PORT=18790
```

Provider API keys have their own env vars (no `NANOBOT_` prefix):
```bash
OPENROUTER_API_KEY=sk-or-v1-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=xxx
GROQ_API_KEY=gsk_xxx
GEMINI_API_KEY=xxx
BRAVE_API_KEY=xxx
```

The `.env` file in the project root is loaded by Docker Compose automatically. Copy `.env.example` to `.env` and fill in values.

## Running Nanobot

### Installation (Host, no Docker)

```bash
# With uv (recommended)
uv tool install /path/to/nanobot       # from source
uv tool install nanobot-ai             # from PyPI

# With pip
pip install -e /path/to/nanobot        # from source
pip install nanobot-ai                 # from PyPI
```

### CLI Commands

```bash
nanobot onboard                # Initialize config & workspace (first time)
nanobot status                 # Show config, providers, and channel status
nanobot agent -m "message"     # Single-shot chat
nanobot agent                  # Interactive chat mode
nanobot agent --no-markdown    # Plain-text replies
nanobot agent --logs           # Show runtime logs during chat
nanobot gateway                # Start the gateway (HTTP + channels)
nanobot channels login         # Link WhatsApp (scan QR code)
nanobot channels status        # Show channel connection status
nanobot cron list              # List scheduled jobs
nanobot cron add --name "job" --message "msg" --cron "0 9 * * *"
nanobot cron remove <job_id>
```

### Docker Compose (Recommended for Production)

The `compose.yml` file defines the nanobot service. The Docker image is built from the included `Dockerfile` using `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` as base, with Node.js 20 for the WhatsApp bridge.

#### First-time setup

```bash
cd /path/to/nanobot
cp .env.example .env
# Edit .env with your API keys

# Initialize config
docker compose run --rm nanobot onboard

# Edit the generated config
vim ~/.nanobot/config.json
```

#### Start / Stop / Restart

```bash
# Start (build if needed, detached)
docker compose up -d --build

# View logs
docker compose logs -f nanobot

# Restart (picks up config changes from ~/.nanobot/config.json)
docker compose restart nanobot

# Stop
docker compose down

# Run a one-off command
docker compose run --rm nanobot agent -m "Hello!"
docker compose run --rm nanobot status
```

#### How the Container Works

- **Entrypoint**: `nanobot` binary. Default command: `status`. Compose overrides to `gateway`.
- **Volume mount**: `~/.nanobot` on host -> `/home/nanobot/.nanobot` in container. This shares config.json and workspace between host and container.
- **Port**: `18790` exposed for the HTTP gateway.
- **User**: Runs as non-root user `nanobot` (UID/GID configurable via `NANOBOT_UID`/`NANOBOT_GID` build args, default 1000).
- **Health check**: Runs `nanobot status` every 60s.
- **Restart policy**: `unless-stopped`.
- **Environment**: Reads `.env` file from the project root (optional).
- **Resource limits**: 1GB memory limit, 256MB reservation (adjustable in compose.yml).

#### Important Docker Caveats

1. **Workspace path**: Must use `~/.nanobot/workspace` (the default) in config.json. Host-absolute paths like `/mnt/apps/...` do not exist inside the container and will cause `PermissionError`.
2. **WhatsApp**: Requires `nanobot channels login` running separately (for QR code scanning). The bridge runs inside the container but the login step is interactive.
3. **Config changes**: Edit `~/.nanobot/config.json` on the host, then `docker compose restart nanobot`. No rebuild needed for config-only changes.
4. **Code changes**: If you modify Python source or the bridge, you must rebuild: `docker compose up -d --build`.

#### Docker Compose Environment Variables

Set in `.env` or in the `environment` section of compose.yml:

| Variable | Purpose |
|---|---|
| `NANOBOT_UID` / `NANOBOT_GID` | Container user UID/GID (build arg, default 1000) |
| `NANOBOT_CONFIG_DIR` | Host path to mount as config dir (default `~/.nanobot`) |
| `OPENROUTER_API_KEY` | OpenRouter LLM provider key |
| `BRAVE_API_KEY` | Brave Search API key |
| `GROQ_API_KEY` | Groq API key (for Whisper voice transcription) |
| `NANOBOT_GATEWAY__HOST` | Gateway bind host |
| `NANOBOT_GATEWAY__PORT` | Gateway bind port |

## Voice Transcription

Voice transcription is handled exclusively by **Groq's Whisper API** (`whisper-large-v3` model). It is NOT available through OpenRouter or other providers.

Requirements:
1. A Groq API key configured in `providers.groq.apiKey` (or `GROQ_API_KEY` env var)
2. **Telegram channel only** -- voice transcription is currently supported only for Telegram voice/audio messages
3. WhatsApp voice messages are received but transcription is not yet implemented (logged as "[Voice Message: Transcription not available for WhatsApp yet]")

## Provider Priority and Model Routing

Provider matching (defined in `providers/registry.py`) follows this priority:

1. **Keyword match**: Model name is checked against each provider's keywords (e.g., "claude" -> anthropic, "gpt" -> openai, "deepseek" -> deepseek)
2. **Gateway fallback**: If no keyword match, gateway providers (openrouter, aihubmix) with valid API keys are tried first
3. **Any available**: Falls back to any provider with a configured API key

Gateway providers like OpenRouter can route any model name. When using OpenRouter, prefix models with their provider path (e.g., `anthropic/claude-opus-4-5`, `openai/gpt-4.1-nano`).

## Security

| Setting | Default | Description |
|---|---|---|
| `tools.restrictToWorkspace` | `false` | Sandboxes all agent tools to workspace directory. Set `true` for production. |
| `channels.*.allowFrom` | `[]` (allow all) | Whitelist of user IDs. Empty = allow everyone. |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "No API key configured" | No provider has a non-empty `apiKey` | Add at least one provider API key to config.json |
| "No channels enabled" | All channels have `enabled: false` | Enable at least one channel, or use CLI mode (`nanobot agent`) |
| `PermissionError: '/mnt/apps'` in Docker | `workspace` path doesn't exist in container | Set `workspace` to `~/.nanobot/workspace` in config.json |
| JSON parse error on config load | Invalid JSON in config.json | Validate with `python3 -m json.tool ~/.nanobot/config.json` |
| Config changes not picked up in Docker | Container needs restart | Run `docker compose restart nanobot` |
| WhatsApp not connecting | Bridge not running | Run `nanobot channels login` in a separate terminal |
| Voice transcription not working | Groq API key missing or wrong channel | Add `groq.apiKey` to providers and use Telegram |
