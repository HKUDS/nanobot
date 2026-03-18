# CLAUDE.md

## Project Overview

Nanobot is a lightweight personal AI assistant framework. It connects to multiple chat platforms (channels), routes messages through an agent loop powered by LLMs (via LiteLLM), and supports tools, cron jobs, and persistent memory.

## Architecture

```
User messages → Channel → MessageBus → AgentLoop → LLM Provider
                                ↓
                          OutboundMessage → Channel → User
```

### Core Components

- **`nanobot/agent/`** — Agent loop (`loop.py`), context building (`context.py`), memory (`memory.py`), skills (`skills.py`), subagent spawning (`subagent.py`)
- **`nanobot/agent/tools/`** — Tool implementations: filesystem, shell, web, cron, MCP, message sending, spawn
- **`nanobot/bus/`** — Message bus (`queue.py`) and event types (`events.py`) — `InboundMessage` / `OutboundMessage`
- **`nanobot/channels/`** — Chat platform integrations. Each channel extends `BaseChannel` (see below)
- **`nanobot/cli/commands.py`** — Typer CLI: `nanobot gateway`, `nanobot agent`, `nanobot channels status`, `nanobot cron`, etc.
- **`nanobot/config/`** — Pydantic config schema (`schema.py`) and JSON loader (`loader.py`)
- **`nanobot/providers/`** — LLM provider abstraction: LiteLLM (`litellm_provider.py`), OpenAI Codex (`openai_codex_provider.py`), registry (`registry.py`)
- **`nanobot/cron/`** — Scheduled job service
- **`nanobot/heartbeat/`** — Periodic heartbeat service
- **`nanobot/session/`** — Session management for conversation persistence

### Bridge (TypeScript)

- **`bridge/`** — Node.js WhatsApp bridge using `@whiskeysockets/baileys`
- **`bridge/src/whatsapp.ts`** — WhatsApp client: connects to WhatsApp Web, handles messages
- **`bridge/src/server.ts`** — WebSocket server bridging Python ↔ WhatsApp client
- Python connects to the bridge via WebSocket at `ws://localhost:3001`
- Bridge is auto-built to `~/.nanobot/bridge/` on first use

## Channels

All channels extend `BaseChannel` from `nanobot/channels/base.py`:
- `start()` — Long-running async task that listens for incoming messages
- `stop()` — Cleanup
- `send(msg: OutboundMessage)` — Send a reply
- `is_allowed(sender_id)` — Check against `allow_from` list
- `_handle_message(sender_id, chat_id, content, media, metadata)` — Validates sender and publishes to bus

Registered in `nanobot/channels/manager.py` `_init_channels()`. Each channel's config lives in `nanobot/config/schema.py` under `ChannelsConfig`.

Available channels: WhatsApp, Telegram, Discord, Feishu, Mochat, DingTalk, Email, Slack, QQ, iMessage.

## Config

- Config file: `~/.nanobot/config.json` (camelCase keys)
- Schema: `nanobot/config/schema.py` (snake_case fields)
- Loader: `nanobot/config/loader.py` — auto-converts camelCase ↔ snake_case via `convert_keys()` / `convert_to_camel()`
- **Important**: Config field names must match camelCase conversion. E.g., `iMessage` in JSON → `i_message` in Pydantic (not `imessage`). Use `camel_to_snake()` to verify.

## Key Patterns

- **Editable install**: Installed via `pip install -e .` in `venv/`. Source changes take effect immediately.
- **Async everywhere**: Channels, agent loop, bus — all asyncio. Gateway runs via `asyncio.run()`.
- **Lazy imports**: Channel implementations are imported inside `_init_channels()` to avoid pulling in unused dependencies.
- **camelCase config**: JSON config uses camelCase, Pydantic models use snake_case. The loader handles conversion both ways.

## Self-Chat Mode

Channels that support `self_chat: bool` (WhatsApp, iMessage) allow processing messages from the user's own account. Used for testing — message yourself and the bot responds.

### WhatsApp Self-Chat
- Config: `channels.whatsapp.self_chat = true`
- Python sends `{"type": "config", "self_chat": true}` to the bridge after connecting
- Bridge (`whatsapp.ts`): when `selfChat=true`, allows `fromMe` messages through (bot replies filtered by `sentMessageIds` tracking)
- When `selfChat=false` (default): all `fromMe` messages are skipped

### iMessage Self-Chat
- Config: `channels.i_message.self_chat = true`
- iMessage delivers each self-chat message as TWO notifications: `is_from_me=true` + `is_from_me=false` (echo)
- Three dedup layers prevent infinite loops:
  1. **Numeric ID dedup** (`_seen_ids`): Echo pairs have consecutive numeric IDs (e.g., 381205 / 381206). Processing one skips the other.
  2. **Sent-text tracking** (`_sent_texts`): Bot reply text is cached by `chat_id:text` *before* sending the RPC (avoids race condition). Echoes of bot replies match the cache.
  3. **`is_from_me=false` filter**: In self-chat mode, only `is_from_me=true` messages are processed.

## iMessage Channel

- Uses `imsg` CLI tool's JSON-RPC 2.0 over stdio mode
- Spawns `imsg rpc` as an asyncio subprocess
- `watch.subscribe` to receive incoming messages as notifications
- `send` RPC to send outbound messages
- Message data is nested inside `params["message"]` in notifications
- Binary auto-detected from: config `imsg_path` → `PATH` → `~/Code/imsg/bin/imsg`
- Auto-reconnects if the subprocess exits

## Development

- Python 3.11+, dependencies in `pyproject.toml`
- Virtualenv: `venv/` — activate with `source venv/bin/activate`
- Install: `pip install -e .` (editable)
- Tests: `pytest` (uses pytest-asyncio)
- Lint: `ruff check nanobot/`
- Bridge rebuild: `cd bridge && npx tsc && rm -rf ~/.nanobot/bridge`
- Entry point: `nanobot` CLI → `nanobot/cli/commands.py:app`
