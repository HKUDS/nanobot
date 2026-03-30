# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is a lightweight AI Agent framework that connects LLMs to multiple messaging channels (Telegram, WeChat, Feishu, DingTalk, Slack, Discord, WhatsApp, QQ, Matrix, Email, etc.). It emphasizes minimal code and maximum reuse of mature libraries.

## Development Commands

```bash
# Install all extras with uv (recommended)
uv sync --all-extras

# Or install in editable mode with pip
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_commands.py

# Run tests matching a pattern
pytest -k "test_onboard"

# Lint
ruff check nanobot/

# Format
ruff format nanobot/

# Auto-fix lint issues
ruff check --fix nanobot/
```

## Architecture

### Data Flow

```
Channel (Telegram/Feishu/etc.)
    → InboundMessage (bus/events.py)
    → MessageBus (bus/queue.py)
    → AgentLoop (agent/loop.py)
        → ContextBuilder (agent/context.py) — assembles system prompt
        → LLM Provider (providers/) — via litellm or direct
        → ToolRegistry (agent/tools/registry.py) — executes tool calls
    → OutboundMessage → Channel
```

### Key Components

**`agent/loop.py`** — Core processing loop. Receives messages, builds context, calls LLM, executes tools, sends responses. The central orchestrator (~623 lines).

**`agent/context.py`** — Builds system prompt by loading workspace files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`) and injecting runtime memory and skills.

**`agent/memory.py`** — `MemoryStore` (read/manage) and `MemoryConsolidator` (compress long-term memory). Memory is persisted in the workspace directory.

**`channels/`** — Each channel implements `BaseChannel` (channels/base.py). `ChannelManager` manages lifecycle. `ChannelRegistry` is the factory. All channels emit `InboundMessage` and consume `OutboundMessage` via the shared `MessageBus`.

**`providers/`** — LLM adapters. `LiteLLMProvider` covers most cases (Anthropic, OpenAI, DeepSeek, Groq, Ollama, vLLM, etc.). `ProviderRegistry` handles auto-discovery. Custom OpenAI-compatible endpoints use `CustomProvider`.

**`config/schema.py`** — Pydantic V2 models for all configuration. User config lives at `~/.nanobot/config.json`.

**`agent/tools/`** — Tools registered into `ToolRegistry`: `filesystem.py` (Read/Write/Edit/ListDir), `shell.py` (Execute), `web.py` (search + fetch), `cron.py` (scheduling), `mcp.py` (Model Context Protocol), `spawn.py` (sub-agent creation), `message.py` (send to channel).

### Workspace Files

At runtime, the agent loads from the user's workspace directory:
- `AGENTS.md` — Agent identity and behavior instructions
- `SOUL.md` — Personality definition
- `USER.md` — User profile
- `TOOLS.md` — Tool usage guidance
- `memory/` — Long-term memories

Templates are in `nanobot/templates/`.

### Branch Strategy

- `main` — stable (bug fixes, docs)
- `nightly` — new features and experiments (cherry-picked to main)

## Code Conventions

- Python 3.11+, full type annotations, Pydantic V2 for data models
- Async throughout (`asyncio`)
- Line length: 100 chars (`ruff`)
- Linting rules: E, F, I, N, W (E501 ignored)
- Loguru for logging (`from loguru import logger`)
- Prefer minimal changes; favor readability over cleverness

## WhatsApp Bridge

`bridge/` contains a TypeScript/Node.js service that bridges WhatsApp (via Baileys) to the Python agent over WebSocket. Requires Node.js 20+. Built and run separately from the Python package.
