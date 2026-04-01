# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**nanobot** is an ultra-lightweight personal AI assistant framework (~4,000 lines of Python). Inspired by OpenClaw, it delivers core agent functionality with 99% less code. It connects to 9+ chat platforms (Telegram, WhatsApp, Discord, Slack, etc.) and supports 15+ LLM providers via LiteLLM.

**Package:** `nanobot-ai` on PyPI | **License:** MIT | **Python:** ≥3.11

## Build and Development Commands

```bash
# Install from source (editable, recommended for development)
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
pytest tests/test_tool_validation.py          # specific test file
pytest tests/test_tool_validation.py -k "test_name"  # specific test

# Lint
ruff check .
ruff check --fix .

# Line count verification
bash core_agent_lines.sh
```

### Running nanobot

```bash
nanobot onboard              # First-time setup (creates ~/.nanobot/)
nanobot agent                # Interactive CLI chat
nanobot agent -m "Hello!"   # Single message
nanobot gateway              # Start multi-channel gateway (Telegram, WhatsApp, etc.)
nanobot status               # Show config/provider status
nanobot cron list            # Show scheduled tasks
nanobot channels status      # Show channel status
nanobot channels login       # Link WhatsApp (QR scan)
nanobot provider login openai-codex  # OAuth login for providers
```

## Architecture

### Core Flow

```
Channel (Telegram/WhatsApp/...) → MessageBus → AgentLoop → LLM → Tools → Response → MessageBus → Channel
```

### Package Structure

```
nanobot/
├── agent/              # Core agent logic
│   ├── loop.py         # Main agent loop (receive → context → LLM → tools → respond)
│   ├── context.py      # Prompt builder (assembles SOUL.md, AGENTS.md, memory, skills)
│   ├── memory.py       # Persistent memory (MEMORY.md + HISTORY.md, LLM-driven consolidation)
│   ├── skills.py       # Skills loader (builtin + workspace skills, SKILL.md format)
│   ├── subagent.py     # Background task execution (spawn tool)
│   └── tools/          # Built-in tools
│       ├── registry.py # Tool registry (central registration)
│       ├── filesystem.py # read_file, write_file, edit_file, list_dir
│       ├── shell.py    # exec (with safety blocklist + timeout)
│       ├── web.py      # web_fetch, web_search (Brave API)
│       ├── message.py  # send_message (cross-channel messaging)
│       ├── spawn.py    # spawn (background subagent tasks)
│       ├── cron.py     # cron management via exec
│       └── mcp.py      # MCP tool proxy
├── channels/           # Chat platform integrations
│   ├── manager.py      # ChannelManager (init, start/stop, route outbound)
│   ├── base.py         # BaseChannel abstract class
│   ├── telegram.py     # Telegram (long polling, voice transcription via Groq)
│   ├── whatsapp.py     # WhatsApp (WebSocket bridge to Node.js Baileys)
│   ├── discord.py      # Discord (WebSocket gateway, message splitting)
│   ├── slack.py        # Slack (Socket Mode)
│   ├── email.py        # Email (IMAP poll + SMTP reply)
│   ├── feishu.py       # Feishu/Lark (WebSocket)
│   ├── mochat.py       # Mochat/Claw IM (Socket.IO)
│   ├── dingtalk.py     # DingTalk (Stream Mode)
│   └── qq.py           # QQ (botpy SDK)
├── bus/                # Async message routing
│   ├── queue.py        # MessageBus (inbound/outbound async queues)
│   └── events.py       # InboundMessage, OutboundMessage dataclasses
├── session/            # Conversation sessions
│   └── manager.py      # Session + SessionManager (JSONL persistence, consolidation cursor)
├── providers/          # LLM provider abstraction
│   ├── registry.py     # ProviderSpec registry (single source of truth for all providers)
│   ├── base.py         # LLMProvider base (LiteLLM wrapper + prompt caching)
│   └── custom.py       # CustomProvider (direct OpenAI-compatible, bypasses LiteLLM)
├── config/
│   └── schema.py       # Pydantic config schema (Config → agents, channels, providers, tools)
├── cron/               # Scheduled tasks (croniter-based)
├── heartbeat/          # Periodic wake-up (every 30min, reads HEARTBEAT.md)
├── skills/             # Bundled skills
│   ├── clawhub/        # Search & install public agent skills
│   ├── cron/           # Cron management skill
│   ├── github/         # GitHub integration
│   ├── memory/         # Memory management
│   ├── skill-creator/  # Create new skills
│   ├── summarize/      # Text summarization
│   ├── tmux/           # Terminal multiplexer
│   └── weather/        # Weather forecasts
├── templates/          # Bootstrap prompt templates (injected into system prompt)
│   ├── AGENTS.md       # Agent behavior guidelines
│   ├── SOUL.md         # Personality and values
│   ├── USER.md         # User-specific context
│   ├── TOOLS.md        # Tool usage notes
│   ├── HEARTBEAT.md    # Periodic task template
│   └── memory/
│       └── MEMORY.md   # Memory template
├── cli/
│   └── commands.py     # Typer CLI (nanobot agent|gateway|status|cron|channels|onboard)
└── utils/
    └── helpers.py      # ensure_dir, safe_filename, etc.

bridge/                 # WhatsApp bridge (Node.js, Baileys, bundled in wheel)
tests/                  # pytest tests (asyncio_mode = "auto")
```

### Key Architectural Patterns

- **MessageBus** — Async queues decouple channels from agent. Channels push `InboundMessage`, agent pushes `OutboundMessage`. Fully async.

- **Sessions** — JSONL-backed, append-only for LLM cache efficiency. Consolidation writes summaries to memory files but doesn't modify message history. Cursor (`last_consolidated`) tracks progress.

- **ContextBuilder** — Assembles system prompt from bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`) + `memory/MEMORY.md` + skills. Files are read from `~/.nanobot/workspace/`.

- **Memory** — Two-tier: `MEMORY.md` (persistent facts, updated by LLM) + `HISTORY.md` (chronological event log). Consolidation is LLM-driven via a `save_memory` tool call.

- **Skills** — Markdown files (`SKILL.md`) that inject instructions into the agent's context. Workspace skills (`~/.nanobot/workspace/skills/`) override builtins.

- **Provider Registry** — `ProviderSpec` dataclass in `registry.py` is the single source of truth. Adding a provider = 1 spec entry + 1 Pydantic field. Handles env vars, model prefixing, keyword matching, fallback order.

- **Config** — Pydantic models accepting both `camelCase` and `snake_case` (JSON config uses camelCase). Stored at `~/.nanobot/config.json`. Env override via `NANOBOT_` prefix.

## Configuration

Runtime config lives at `~/.nanobot/config.json`. Key sections:

| Section | Purpose |
|---------|---------|
| `agents.defaults` | model, maxTokens, temperature, workspace, memoryWindow |
| `channels.*` | Per-channel config (enabled, token, allowFrom) |
| `providers.*` | API keys and base URLs for LLM providers |
| `tools.mcpServers` | MCP server connections (stdio or HTTP) |
| `tools.restrictToWorkspace` | Sandbox mode (default false) |
| `gateway` | Host/port (default 0.0.0.0:18790) |

## Testing

```bash
pytest                    # Run all tests
pytest -x                 # Stop on first failure
pytest -k "cron"          # Run tests matching pattern
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. Test files are in `tests/`.

## Code Style

- **Linter:** ruff (line-length 100, target py311)
- **Rules:** E, F, I, N, W (E501 ignored — no line length enforcement)
- **Types:** Pydantic models for config, dataclasses for internal state
- **Logging:** loguru throughout (`from loguru import logger`)
- **Async:** asyncio for all I/O (channels, bus, agent loop, heartbeat)

## Important Notes

- The `custom` provider bypasses LiteLLM entirely — model name is passed as-is to the OpenAI-compatible endpoint
- WhatsApp requires a separate Node.js bridge process (`bridge/`) communicating via WebSocket
- `allowFrom: []` (empty) means open access; non-empty restricts to listed IDs
- The agent's workspace (`~/.nanobot/workspace/`) contains SOUL.md, AGENTS.md, memory/, sessions/, and skills/
- Heartbeat runs every 30 minutes in gateway mode, reading HEARTBEAT.md for periodic tasks
- Session messages are append-only; consolidation only updates memory files, never rewrites history
