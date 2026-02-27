# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Workflow

This repo is a fork of `HKUDS/nanobot`. NEVER push to or open PRs against `HKUDS/nanobot` (upstream). ALWAYS push and open PRs against `taobojlen/nanobot` (origin).

## Development Commands

```bash
# Install for development
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_message_tool.py

# Run a single test by name
pytest tests/test_message_tool.py::test_function_name -v

# Lint
ruff check nanobot/

# Format
ruff format nanobot/

# Check line count (core agent code target: ~4000 lines)
bash core_agent_lines.sh

# Run the CLI
nanobot agent -m "Hello"
nanobot gateway
nanobot status
```

Linting: ruff with `line-length = 100`, selects E/F/I/N/W, ignores E501 (long lines). Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).

## Architecture

nanobot is an ultra-lightweight agent framework (~4000 lines). The core data flow is:

```
Chat Channel → MessageBus (inbound queue) → AgentLoop → LLM + Tools → MessageBus (outbound queue) → Chat Channel
```

### Key Components

**`nanobot/bus/`** — Async `MessageBus` with two `asyncio.Queue`s (inbound/outbound). Completely decouples channels from the agent. `InboundMessage` and `OutboundMessage` are the wire types.

**`nanobot/agent/loop.py`** — `AgentLoop`: the core engine. Consumes `InboundMessage`s, calls `ContextBuilder.build_messages()`, runs the LLM tool-call loop (up to `max_iterations=40`), executes tools, saves the session, and publishes the `OutboundMessage`. Handles `/new`, `/stop`, `/help` slash commands. Memory consolidation triggers asynchronously when unconsolidated messages exceed `memory_window`.

**`nanobot/agent/context.py`** — `ContextBuilder` assembles the full LLM prompt: identity + bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md` from workspace) + memory + skills summary. A runtime context block (current time, channel, chat ID) is injected as a separate user message before each user turn.

**`nanobot/agent/memory.py`** — `MemoryStore`: two-layer persistent memory. `MEMORY.md` (long-term facts) + `HISTORY.md` (grep-searchable log). Consolidation is triggered by `AgentLoop` and uses a dedicated LLM call with a `save_memory` tool to extract facts and write to disk.

**`nanobot/agent/skills.py`** — `SkillsLoader`: discovers skills from `workspace/skills/` (higher priority) and bundled `nanobot/skills/`. Skills are `SKILL.md` files with YAML frontmatter. Skills with `always: true` in frontmatter are auto-loaded into every prompt. Others appear as a summary; the agent reads the full content on demand.

**`nanobot/agent/subagent.py`** — `SubagentManager`: spawns background tasks via the `spawn` tool. Each subagent runs its own tool-execution loop and reports results back via the bus.

**`nanobot/agent/tools/`** — Built-in tools: `filesystem` (read/write/edit/list), `shell` (exec), `web` (search via Brave, fetch), `message` (send to a specific channel), `spawn` (background subagent), `cron` (schedule tasks), `mcp` (dynamic MCP server tools). All implement a common `BaseTool` interface with `get_definition()` and `execute()`. `ToolRegistry` holds them all.

**`nanobot/channels/`** — `BaseChannel` ABC with `start()`, `stop()`, `send()`. `ChannelManager` initializes enabled channels from config and dispatches outbound messages. Each channel (Telegram, Discord, Slack, etc.) pushes `InboundMessage`s to the bus and implements `send()` for outbound. Session key is `channel:chat_id`; threads can override this.

**`nanobot/providers/`** — `ProviderRegistry` (`registry.py`) is the single source of truth. Provider matching priority: explicit `provider` config → model-name keyword → API key/base auto-detection → first available. Most providers route through LiteLLM; `custom` provider and OAuth providers bypass it. Adding a provider = 2 steps: `ProviderSpec` in `registry.py` + field in `ProvidersConfig` in `config/schema.py`.

**`nanobot/session/manager.py`** — Sessions stored as JSONL at `workspace/sessions/{channel_chat_id}.jsonl`. Each file has a metadata header line (`_type: metadata`) followed by message lines. `last_consolidated` tracks the consolidation watermark. `get_history()` returns only unconsolidated messages, aligned to start at a user turn.

**`nanobot/config/schema.py`** — Pydantic models with `alias_generator=to_camel` (accepts both camelCase and snake_case). Root `Config` class uses `pydantic-settings` with `env_prefix="NANOBOT_"` and `env_nested_delimiter="__"`. Config file lives at `~/.nanobot/config.json`.

**`nanobot/cron/`** and **`nanobot/heartbeat/`** — Cron runs scheduled tasks via the agent. Heartbeat wakes every 30 minutes and runs tasks defined in `workspace/HEARTBEAT.md`.

**`bridge/`** — Node.js WhatsApp bridge (separate process). Packaged into the wheel under `nanobot/bridge/` via `force-include` in `pyproject.toml`.

### Workspace Layout (`~/.nanobot/workspace/`)

```
workspace/
├── memory/
│   ├── MEMORY.md      # Long-term facts (LLM-maintained)
│   └── HISTORY.md     # Grep-searchable conversation log
├── sessions/          # Per-channel JSONL session files
├── skills/            # User-installed custom skills
├── HEARTBEAT.md       # Periodic tasks (run every 30 min)
├── AGENTS.md          # Agent personality/instructions
└── SOUL.md / USER.md / TOOLS.md / IDENTITY.md  # Optional bootstrap files
```

### Adding a New Channel

1. Create `nanobot/channels/mychannel.py` with a class extending `BaseChannel`.
2. Add config class to `nanobot/config/schema.py` and register it in `ChannelsConfig`.
3. Add initialization in `ChannelManager._init_channels()`.
