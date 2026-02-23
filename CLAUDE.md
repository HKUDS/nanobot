# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI assistant framework (~4,000 lines of core code) written in Python. It provides:

- Multi-channel chat support (Telegram, Discord, Slack, Feishu, WhatsApp, Email, QQ, DingTalk, Mochat)
- Multi-LLM provider support (OpenRouter, Anthropic, OpenAI, DeepSeek, Groq, Gemini, Zhipu, Qwen, Moonshot, MiniMax, vLLM, and more)
- Built-in tools (filesystem, shell, web search, web fetch, message, spawn, cron)
- MCP (Model Context Protocol) support
- Memory consolidation and session management
- Scheduled tasks (cron)

## Development Setup

```bash
# Install from source (editable mode)
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"
```

## Common Commands

```bash
# Run the agent in CLI mode
nanobot agent -m "Hello!"
nanobot agent  # interactive mode

# Start the gateway for chat channels
nanobot gateway

# Initialize configuration
nanobot onboard

# Show status
nanobot status

# Cron commands
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron list
nanobot cron remove <job_id>

# Provider OAuth login
nanobot provider login openai-codex

# Channel management
nanobot channels login  # WhatsApp QR scan
nanobot channels status
```

## Code Structure

```
nanobot/
├── agent/              # Core agent logic
│   ├── loop.py         # Agent loop (LLM ↔ tool execution)
│   ├── context.py      # Prompt builder
│   ├── memory.py       # Persistent memory
│   ├── skills.py       # Skills loader
│   ├── subagent.py     # Background task execution
│   └── tools/          # Built-in tools
├── skills/             # Bundled skills (github, weather, tmux...)
├── channels/           # Chat channel integrations
├── bus/                # Message routing (InboundMessage, OutboundMessage)
├── cron/               # Scheduled tasks
├── heartbeat/          # Proactive wake-up
├── providers/          # LLM providers
│   ├── registry.py     # Provider registry (add new providers here)
│   └── base.py         # LLMProvider abstract base class
├── session/            # Conversation sessions
├── config/             # Configuration (Pydantic schema)
└── cli/                # Typer CLI commands
```

## Key Architecture Concepts

### Message Flow

1. **Channels** receive messages from chat platforms and create `InboundMessage`
2. **MessageBus** queues messages for processing
3. **AgentLoop** consumes messages, builds context, calls LLM, executes tools
4. **AgentLoop** creates `OutboundMessage` which is routed back to channels

### Adding a New LLM Provider

Two-step process (no if-elif chains):

1. Add a `ProviderSpec` to `PROVIDERS` in `nanobot/providers/registry.py`
2. Add a field to `ProvidersConfig` in `nanobot/config/schema.py`

See `nanobot/providers/registry.py` for the `ProviderSpec` dataclass and examples.

### Adding a New Chat Channel

1. Create a channel module in `nanobot/channels/`
2. Inherit from `BaseChannel` in `nanobot/channels/base.py`
3. Implement `start()` method that listens for messages and publishes `InboundMessage` to bus
4. Implement `send(message: OutboundMessage)` method
5. Register in `nanobot/channels/manager.py`

### Configuration

- Config file: `~/.nanobot/config.json`
- Schema: `nanobot/config/schema.py` (Pydantic models)
- Supports both camelCase and snake_case
- Environment variable override: `NANOBOT_` prefix with `__` nesting (e.g. `NANOBOT_AGENTS__DEFAULTS__MODEL`)

## Testing & Linting

```bash
# Run tests
pytest tests/
pytest tests/test_commands.py -v  # specific test file

# Lint
ruff check nanobot/
ruff check --fix nanobot/  # auto-fix
```

## Important Files

- `nanobot/agent/loop.py` - Core agent processing loop
- `nanobot/providers/registry.py` - Provider registry (add new providers here)
- `nanobot/config/schema.py` - Configuration schema
- `nanobot/cli/commands.py` - CLI commands
- `nanobot/bus/events.py` - `InboundMessage` and `OutboundMessage` dataclasses
- `nanobot/channels/base.py` - Base channel interface

## Bridge (WhatsApp)

The `bridge/` directory contains a TypeScript/Node.js WhatsApp bridge using Baileys.

```bash
cd bridge/
npm install
npm run build
npm start
```
