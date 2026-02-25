# nanobot Architecture

A detailed technical reference for developers who want to understand, research, improve, or extend nanobot.

---

## Table of Contents

1. [Overview](#overview)
2. [Repository Structure](#repository-structure)
3. [Message Flow](#message-flow)
4. [Core Modules](#core-modules)
5. [Capabilities](#capabilities)
6. [Data Model & Persistence](#data-model--persistence)
7. [Configuration](#configuration)
8. [Deployment](#deployment)
9. [Extension Points](#extension-points)
10. [Runtime Dependencies](#runtime-dependencies)

---

## Overview

nanobot is a **message-driven AI agent runtime** built around an async message bus. Chat channels (Telegram, WhatsApp, Discord, etc.) publish inbound messages; the agent processes them via an LLM with tools, then publishes outbound responses. Channels consume outbound messages and deliver them to users.

**Key design principles:**
- **Decoupled channels**: Channels never call the agent directly; they use the bus.
- **Session isolation**: Each `channel:chat_id` has its own session and history.
- **Tool-based actions**: The LLM uses function calling; tools are registered in a registry.
- **Provider abstraction**: Multiple LLM backends (OpenAI, Anthropic, OpenRouter, etc.) via a unified interface.
- **Progressive skill loading**: Skills can be always-loaded or on-demand via `read_file`.

---

## Repository Structure

```
nanobot/
├── nanobot/                    # Main Python package
│   ├── __init__.py            # Package entry, version, logo
│   ├── __main__.py             # Entrypoint: python -m nanobot → cli.commands.app
│   ├── agent/                  # Core agent logic
│   │   ├── loop.py             # AgentLoop — main processing engine
│   │   ├── context.py          # ContextBuilder — prompt assembly
│   │   ├── memory.py           # MemoryStore — MEMORY.md / HISTORY.md
│   │   ├── skills.py          # SkillsLoader — skill discovery/loading
│   │   ├── subagent.py        # SubagentManager — background tasks
│   │   └── tools/             # Built-in tools
│   │       ├── base.py         # Tool ABC
│   │       ├── registry.py    # ToolRegistry
│   │       ├── filesystem.py  # read_file, write_file, edit_file, list_dir
│   │       ├── shell.py       # exec
│   │       ├── web.py         # web_search, web_fetch
│   │       ├── message.py     # message (send to channel)
│   │       ├── spawn.py       # spawn (subagent)
│   │       ├── cron.py        # cron (schedule jobs)
│   │       └── mcp.py         # MCPToolWrapper — Model Context Protocol
│   ├── bus/                    # Message routing
│   │   ├── queue.py           # MessageBus — async queues
│   │   └── events.py          # InboundMessage, OutboundMessage
│   ├── channels/               # Chat platform integrations
│   │   ├── base.py            # BaseChannel ABC
│   │   ├── manager.py         # ChannelManager
│   │   ├── telegram.py        # TelegramChannel
│   │   ├── discord.py         # DiscordChannel
│   │   ├── whatsapp.py        # WhatsAppChannel (WebSocket → bridge)
│   │   ├── feishu.py          # FeishuChannel
│   │   ├── slack.py           # SlackChannel
│   │   ├── email.py           # EmailChannel
│   │   ├── mochat.py          # MochatChannel
│   │   ├── dingtalk.py        # DingTalkChannel
│   │   └── qq.py              # QQChannel
│   ├── config/                 # Configuration
│   │   ├── schema.py          # Config, ProvidersConfig, ChannelsConfig, etc.
│   │   └── loader.py          # load_config(), save_config()
│   ├── providers/              # LLM provider abstractions
│   │   ├── base.py            # LLMProvider ABC, LLMResponse, ToolCallRequest
│   │   ├── registry.py        # PROVIDERS tuple, ProviderSpec
│   │   ├── litellm_provider.py
│   │   ├── custom_provider.py
│   │   ├── openai_codex_provider.py
│   │   └── transcription.py  # Voice transcription (Groq Whisper)
│   ├── session/                # Conversation sessions
│   │   └── manager.py         # SessionManager, Session
│   ├── cron/                   # Scheduled tasks
│   │   ├── service.py         # CronService
│   │   └── types.py           # CronJob, CronSchedule, CronStore
│   ├── heartbeat/              # Proactive wake-up
│   │   └── service.py         # HeartbeatService
│   ├── cli/                    # Command-line interface
│   │   └── commands.py        # Typer app, all commands
│   ├── skills/                 # Built-in skills (SKILL.md files)
│   └── utils/
│       └── helpers.py
├── bridge/                     # WhatsApp bridge (Node.js/TypeScript)
│   ├── src/
│   │   ├── index.ts
│   │   └── server.ts          # BridgeServer (WebSocket + Baileys)
│   └── package.json
├── pyproject.toml
├── Dockerfile
└── README.md
```

---

## Message Flow

### High-Level Flow

```
┌─────────────┐     publish_inbound      ┌─────────────┐     consume_inbound
│   Channel   │ ──────────────────────► │  MessageBus │ ◄──────────────────
│ (Telegram,  │                          │  (inbound   │
│  WhatsApp,  │                          │   queue)    │
│  CLI, etc.) │                          └──────┬──────┘
└─────────────┘                                 │
                                                │ consume
                                                ▼
                                         ┌─────────────┐
                                         │ AgentLoop   │
                                         │ - Session   │
                                         │ - Context   │
                                         │ - LLM call  │
                                         │ - Tools     │
                                         └──────┬──────┘
                                                │ publish_outbound
                                                ▼
┌─────────────┐     send()               ┌─────────────┐     consume_outbound
│   Channel   │ ◄─────────────────────── │  MessageBus │ ────────────────────
│             │                          │  (outbound  │
│             │                          │   queue)    │
└─────────────┘                          └─────────────┘
```

### Inbound Flow (User → Agent)

1. **Channel receives message** (e.g., Telegram webhook, WhatsApp bridge WebSocket).
2. **Permission check**: `channel.is_allowed(sender_id)` — uses `allow_from` list if configured.
3. **Create InboundMessage**:
   - `channel`: e.g. `"telegram"`, `"whatsapp"`, `"cli"`
   - `sender_id`: user identifier
   - `chat_id`: chat/channel identifier
   - `content`: message text
   - `media`: optional list of local file paths (images, voice)
   - `metadata`: channel-specific data (message_id, etc.)
4. **Publish**: `await bus.publish_inbound(msg)`.
5. **AgentLoop.run()** consumes via `bus.consume_inbound()` (blocks with 1s timeout for graceful shutdown).
6. **AgentLoop._process_message()**:
   - Resolve session: `session_manager.get_or_create(session_key)` where `session_key = f"{channel}:{chat_id}"`.
   - Handle slash commands: `/new` (clear + consolidate), `/help` (return help text).
   - Trigger async memory consolidation if `len(session.messages) > memory_window`.
   - Set tool context (channel, chat_id) for `message`, `spawn`, `cron` tools.
   - Build messages: `context.build_messages(history, current_message, media, channel, chat_id)`.
   - Run agent loop: `_run_agent_loop()` — LLM call, tool execution, repeat until no tool calls.
   - Save session: `session.add_message()`, `session_manager.save()`.
   - Publish `OutboundMessage` via `bus.publish_outbound()`.

### Outbound Flow (Agent → User)

1. **AgentLoop** produces `OutboundMessage` with `channel`, `chat_id`, `content`, optional `media`, `metadata`.
2. **Progress updates**: `metadata._progress = True` — channels can show "thinking..." or tool hints.
3. **ChannelManager._dispatch_outbound()** runs a loop: `bus.consume_outbound()` → route by `msg.channel` → `channel.send(msg)`.
4. **Channel.send()** uses platform API (Telegram Bot API, WhatsApp bridge WebSocket, etc.) to deliver.

### Special Flows

- **System messages**: `channel="system"` — used by subagents to inject results back into a conversation. `chat_id` format: `"origin_channel:origin_chat_id"`.
- **Cron jobs**: `agent.process_direct()` with `session_key=f"cron:{job.id}"`. Optional: `deliver=True` publishes response to a channel.
- **Heartbeat**: `agent.process_direct()` with `session_key="heartbeat"`; agent reads `HEARTBEAT.md` and executes tasks.

---

## Core Modules

### AgentLoop (`agent/loop.py`)

The central processing engine. Responsibilities:

- Consume inbound messages from the bus.
- Build context (system prompt, history, memory, skills).
- Call LLM via provider abstraction.
- Execute tool calls in a loop until the model returns final content.
- Persist sessions and trigger memory consolidation.
- Publish outbound responses.

Key methods:
- `run()` — main loop, consumes inbound, calls `_process_message()`.
- `_process_message()` — process one message, return `OutboundMessage`.
- `process_direct()` — bypass bus for CLI/cron/heartbeat.
- `_run_agent_loop()` — LLM + tool iteration.

### MessageBus (`bus/queue.py`)

Async queues decoupling channels from the agent:

- `inbound: asyncio.Queue[InboundMessage]`
- `outbound: asyncio.Queue[OutboundMessage]`
- `publish_inbound()`, `consume_inbound()`, `publish_outbound()`, `consume_outbound()`

### ContextBuilder (`agent/context.py`)

Assembles the system prompt and message list for the LLM:

- Identity section (runtime, workspace path).
- Bootstrap files: `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`.
- Memory: `workspace/memory/MEMORY.md`.
- Skills: always-loaded skills + summary of available skills.
- History: recent messages from session.
- Current user message (with optional base64 image attachments).

### SessionManager (`session/manager.py`)

Manages conversation sessions per `channel:chat_id`:

- Storage: JSONL in `workspace/sessions/{safe_key}.jsonl`.
- Format: metadata line (`_type: metadata`) + message lines (append-only).
- `get_or_create()`, `save()`, `invalidate()`.
- Legacy migration: `~/.nanobot/sessions/` → `workspace/sessions/`.

### ChannelManager (`channels/manager.py`)

Initializes and coordinates channels:

- `_init_channels()` — instantiate enabled channels from config.
- `start_all()` — start outbound dispatcher + all channels.
- `_dispatch_outbound()` — consume outbound queue, route to `channel.send()`.
- `stop_all()` — stop dispatcher and channels.

### MemoryStore (`agent/memory.py`)

Two-layer memory:

- **MEMORY.md**: Long-term facts (updated by consolidation).
- **HISTORY.md**: Grep-searchable event log (append-only).

Consolidation: when session exceeds `memory_window`, an LLM call summarizes old messages and updates both files via a `save_memory` tool.

### CronService (`cron/service.py`)

Scheduled jobs:

- Storage: `~/.nanobot/cron/jobs.json`.
- Schedule types: `every` (interval), `cron` (expression), `at` (one-shot).
- Callback: `on_job(job)` → `agent.process_direct()`.
- Optional delivery to channel.

### HeartbeatService (`heartbeat/service.py`)

Periodic wake-up (default: every 30 minutes):

- Reads `workspace/HEARTBEAT.md`.
- If actionable content exists, calls `on_heartbeat(HEARTBEAT_PROMPT)` → `agent.process_direct()`.
- Agent replies `HEARTBEAT_OK` if nothing to do.

---

## Capabilities

### Built-in Tools

| Tool        | Module       | Description                                      |
|-------------|--------------|--------------------------------------------------|
| read_file   | filesystem   | Read file contents                               |
| write_file  | filesystem   | Write content to file                             |
| edit_file   | filesystem   | Replace old_text with new_text in file            |
| list_dir    | filesystem   | List directory contents                          |
| exec        | shell        | Execute shell command (with safety guards)        |
| web_search  | web          | Brave Search API                                  |
| web_fetch   | web          | Fetch and extract web page content                |
| message     | message      | Send message to a channel (e.g. WhatsApp)        |
| spawn       | spawn        | Run subagent for background task                 |
| cron        | cron         | Add/remove scheduled jobs (when CronService set)  |

MCP tools are registered dynamically from configured servers (prefix: `mcp_{server}_{tool}`).

### Skills

- **Location**: `workspace/skills/{name}/SKILL.md` (user) or `nanobot/skills/{name}/SKILL.md` (built-in).
- **Format**: YAML frontmatter + markdown body.
- **Progressive loading**: `always=true` skills are fully loaded; others appear as a summary. Agent uses `read_file` to load on demand.
- **Requirements**: `requires.bins[]`, `requires.env[]` — skills with unmet deps are marked unavailable.

### LLM Providers

- **LiteLLMProvider**: Routes to many backends (OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, etc.) via `providers/registry.py`.
- **CustomProvider**: Direct OpenAI-compatible endpoint.
- **OpenAICodexProvider**: OAuth-based (no API key).
- Model selection: config `agents.defaults.model`; provider matched by model prefix/keywords.

### Channels

| Channel   | Protocol / SDK           | Notes                                  |
|-----------|---------------------------|----------------------------------------|
| Telegram  | python-telegram-bot       | Polling, voice transcription (Groq)   |
| WhatsApp  | Node bridge + Baileys     | WebSocket to `ws://localhost:3001`     |
| Discord   | discord.py                | Gateway WebSocket                       |
| Slack     | slack-sdk                 | Socket Mode (no public URL)            |
| Feishu    | lark-oapi                 | WebSocket long connection               |
| DingTalk  | dingtalk-stream           | Stream Mode                             |
| Email     | IMAP + SMTP               | Polling, `consent_granted` required    |
| Mochat    | python-socketio           | Socket.IO WebSocket                     |
| QQ        | qq-botpy                  | WebSocket                               |
| CLI       | prompt_toolkit            | Interactive or single-message mode      |

---

## Data Model & Persistence

### Configuration

- **Path**: `~/.nanobot/config.json`
- **Schema**: Pydantic with camelCase aliases (`Config`, `AgentsConfig`, `ChannelsConfig`, `ProvidersConfig`, etc.)
- **Loading**: `config.loader.load_config()` → `Config.model_validate()`
- **Migration**: `_migrate_config()` for legacy formats

### Sessions

- **Path**: `workspace/sessions/{channel}_{chat_id}.jsonl`
- **Format**: First line = metadata JSON; subsequent lines = message JSON (append-only)
- **Key**: `channel:chat_id` (e.g. `telegram:123456789`)

### Memory

- **MEMORY.md**: Long-term facts, updated by consolidation
- **HISTORY.md**: Event log, append-only, grep-searchable

### Cron

- **Path**: `~/.nanobot/cron/jobs.json`
- **Structure**: `jobs[]` with `schedule`, `payload`, `state`

### WhatsApp Auth

- **Path**: `~/.nanobot/whatsapp-auth/` (used by Node bridge)

### Workspace Layout

```
workspace/
├── AGENTS.md       # Agent instructions
├── SOUL.md         # Personality
├── USER.md         # User info
├── HEARTBEAT.md    # Proactive tasks
├── memory/
│   ├── MEMORY.md
│   └── HISTORY.md
├── sessions/
│   └── *.jsonl
└── skills/
    └── {name}/
        └── SKILL.md
```

---

## Configuration

### Key Config Sections

- **agents.defaults**: `workspace`, `model`, `max_tokens`, `temperature`, `memory_window`, `max_tool_iterations`
- **channels**: Per-channel configs (e.g. `telegram.token`, `whatsapp.bridge_url`, `discord.token`)
- **providers**: Per-provider `api_key`, `api_base`, `extra_headers`
- **tools**: `web.search.api_key`, `exec.timeout`, `restrict_to_workspace`, `mcp_servers`

### Provider Matching

Config matches provider by:
1. Model prefix (e.g. `anthropic/claude-*` → Anthropic)
2. Keywords in model name
3. Fallback to first provider with API key (gateways first)

### MCP Servers

```json
"mcpServers": {
  "server_name": {
    "command": "npx",
    "args": ["-y", "some-mcp-server"],
    "env": {}
  }
}
```

Or HTTP mode: `"url": "https://...", "headers": {}`

---

## Deployment

### CLI Modes

- **Single message**: `nanobot agent -m "Hello"`
- **Interactive**: `nanobot agent` (prompt_toolkit loop)
- **Gateway**: `nanobot gateway` (channels + agent + cron + heartbeat)

### Docker

- **Base**: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- **Node.js**: Node 20 installed for WhatsApp bridge
- **Build**: `uv pip install`, then `npm install && npm run build` in `bridge/`
- **Volume**: `~/.nanobot` for config persistence
- **Port**: 18790 (gateway)

### WhatsApp Bridge

- **Separate process**: Run `nanobot channels login` to start bridge (QR scan).
- **Gateway mode**: Bridge must run alongside gateway; Python `WhatsAppChannel` connects to `ws://localhost:3001`.
- **Node requirement**: Node.js >= 20 (Baileys dependency)

### Environment Variables

- Config supports `NANOBOT_` prefix and nested `__` delimiter.
- Provider API keys can be set via env (e.g. `OPENROUTER_API_KEY`) or in config.

---

## Extension Points

### Adding a Tool

1. Implement `Tool` ABC (`agent/tools/base.py`): `name`, `description`, `parameters`, `execute()`.
2. Register in `AgentLoop._register_default_tools()` or before processing.

### Adding a Provider

1. Add `ProviderSpec` to `PROVIDERS` in `providers/registry.py`.
2. Add field to `ProvidersConfig` in `config/schema.py`.
3. Implement provider class if not using LiteLLM (e.g. `CustomProvider`, `OpenAICodexProvider`).

### Adding a Channel

1. Extend `BaseChannel` (`channels/base.py`).
2. Implement `start()`, `stop()`, `send()`.
3. Use `_handle_message()` for inbound → `bus.publish_inbound()`.
4. Add to `ChannelManager._init_channels()` and config schema.

### Adding MCP Tools

Configure `tools.mcp_servers` in config. Tools are discovered and registered on startup.

### Adding Skills

Place `SKILL.md` in `workspace/skills/{name}/` with YAML frontmatter. Use `always: true` for always-loaded skills.

---

## Runtime Dependencies

### Python (>= 3.11)

- **Core**: typer, pydantic, litellm, loguru, rich, websockets, httpx
- **Channels**: python-telegram-bot, discord.py, slack-sdk, lark-oapi, dingtalk-stream, qq-botpy, python-socketio
- **Tools**: croniter, readability-lxml
- **MCP**: mcp, json-repair
- **OAuth**: oauth-cli-kit
- **CLI**: prompt-toolkit

### Node.js (>= 20, for WhatsApp bridge)

- @whiskeysockets/baileys, ws, qrcode-terminal, pino

### Optional

- Groq API key for Telegram voice transcription
- Brave Search API key for web_search tool

---

## Testing

- **Config**: `pyproject.toml` defines `pytest`, `pytest-asyncio`, `testpaths = ["tests"]`
- **Current state**: No `tests/` directory in repository

---

## Security Considerations

- **Exec tool**: Deny patterns block dangerous commands (rm -rf, format, etc.). Optional `restrict_to_workspace` limits path access.
- **File tools**: `allowed_dir` can restrict to workspace when `restrict_to_workspace=True`.
- **WhatsApp bridge**: Binds to `127.0.0.1` only; optional `bridge_token` for auth.
- **Channels**: `allow_from` list restricts which users can interact (empty = allow all).
