# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI assistant framework (~3,500 lines of core agent code). Python 3.11+, MIT license.

## Commands

```bash
# Install (development)
pip install -e .
pip install -e ".[dev]"    # with dev deps

# Run
nanobot onboard            # First-time setup (creates ~/.nanobot/)
nanobot agent -m "..."     # Single message
nanobot agent              # Interactive chat
nanobot gateway            # Run all channels (Telegram, Discord, etc.)
nanobot status             # Show config & provider status

# Test
pytest                     # All tests
pytest tests/test_foo.py   # Single file
pytest -s                  # With stdout

# Lint
ruff check nanobot/
ruff format nanobot/
```

Config: `~/.nanobot/config.json`. Workspace: `~/.nanobot/workspace/`.

## Architecture

```
Message Flow:

Channel (Telegram/Discord/...) → InboundMessage → MessageBus
    → AgentLoop → Session + ContextBuilder + LLM Provider
    → Tool execution loop (up to max_iterations)
    → OutboundMessage → MessageBus → Channel.send()
```

### Core Modules

**`agent/loop.py`** — The brain. Receives `InboundMessage`, builds context, calls LLM, executes tools in a loop, returns `OutboundMessage`. Key params: `max_iterations` (default 20), `restrict_to_workspace`.

**`agent/context.py`** — Assembles the system prompt from: core identity → bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`) → memory (long-term + recent 7 days) → always-on skills → skills summary.

**`agent/memory.py`** — `MemoryStore` manages `~/.nanobot/workspace/memory/`. Daily notes as `YYYY-MM-DD.md`, long-term in `MEMORY.md`.

**`agent/skills.py`** — `SkillsLoader` discovers skills from `nanobot/skills/` (built-in) and `~/.nanobot/workspace/skills/` (user). Three-level progressive loading: metadata only → full SKILL.md → bundled scripts/assets.

**`agent/tools/`** — Tool system. `base.py` defines abstract `Tool` (properties: `name`, `description`, `parameters`; method: `async execute(**kwargs) -> str`). `registry.py` manages registration/execution/schema export.

**`bus/`** — Async queue. `InboundMessage`/`OutboundMessage` dataclasses in `events.py`, `MessageBus` queue in `queue.py`.

**`session/manager.py`** — JSONL-based conversation persistence. One file per chat: `~/.nanobot/sessions/{channel}_{chat_id}.jsonl`.

**`channels/`** — Chat platform integrations. All inherit `BaseChannel` (3 abstract methods: `start`, `stop`, `send`). Access control via `allowFrom` lists. Supported: Telegram, Discord, WhatsApp, Feishu, DingTalk, Slack, Email, QQ, Mochat.

**`providers/`** — LLM support via LiteLLM. `base.py` defines `LLMProvider` (method: `async chat() -> LLMResponse`). `registry.py` has `ProviderSpec` for auto-routing (key detection, model prefix, env vars). Supports: OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, DashScope/Qwen, Moonshot/Kimi, Groq, vLLM, etc.

**`config/`** — Pydantic v2 models in `schema.py`, loaded from `~/.nanobot/config.json` by `loader.py`.

### Built-in Tools

Registered in `AgentLoop._register_default_tools()`:
- `read_file`, `write_file`, `edit_file`, `list_dir` — filesystem (optionally restricted to workspace)
- `exec` — shell with security guards (blocks fork bombs, `rm -rf /`, etc.), 60s timeout
- `web_search` — Brave Search API
- `web_fetch` — HTML → markdown
- `message` — send to chat channel with optional media
- `spawn` — background subagent for long tasks
- `schedule`, `list_jobs`, `remove_job` — cron via `CronTool`
- `mcp__*` — dynamic MCP server tools

## How to Extend

### Add a Tool

Create `nanobot/agent/tools/mytool.py` inheriting `Tool`. Implement `name`, `description`, `parameters` (JSON Schema), `async execute()`. Register in `AgentLoop._register_default_tools()`.

### Add a Skill

Create `nanobot/skills/my-skill/SKILL.md` with YAML frontmatter (`name`, `description`, optional `metadata` with emoji/requires/always). Body is markdown instructions. Agent discovers it automatically. User skills go in `~/.nanobot/workspace/skills/`.

### Add a Channel

Create `nanobot/channels/myplatform.py` inheriting `BaseChannel`. Implement `start()`, `stop()`, `send()`. Add Pydantic config to `config/schema.py`. Register in channel manager.

### Add a Provider

Add `ProviderSpec` to `providers/registry.py` (keywords, env_key, litellm_prefix). Add config field to `config/schema.py`. Auto-routing handles the rest.

## Conventions

- Async-first: all I/O operations use `async`/`await`
- Tools return error strings, never raise exceptions
- Logging via `loguru` (`from loguru import logger`)
- Ruff config: line-length 100, target py311, select E/F/I/N/W, ignore E501
- pytest with `asyncio_mode = "auto"`
- Build system: hatchling
