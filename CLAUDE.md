# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI assistant (~4,000 lines of Python). It provides core agent functionality with tool use, multi-channel chat support (Telegram, WhatsApp, Feishu), scheduled tasks, and extensible skills.

## Build & Development Commands

```bash
# Install from source (recommended for development)
pip install -e .

# Install with optional Feishu support
pip install -e ".[feishu]"

# Install dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check nanobot/

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_specific.py -v
```

## CLI Commands

```bash
nanobot onboard          # Initialize config & workspace
nanobot agent -m "..."   # Single message to agent
nanobot agent            # Interactive chat mode
nanobot gateway          # Start multi-channel gateway
nanobot status           # Show status
nanobot cron list        # List scheduled jobs
```

## Architecture

### Core Flow
```
Channel (Telegram/WhatsApp/Feishu/CLI)
    ↓
MessageBus (bus/)
    ↓
AgentLoop (agent/loop.py)
    ├── ContextBuilder (agent/context.py) - Assembles system prompt
    ├── ToolRegistry (agent/tools/registry.py) - Executes tools
    ├── SessionManager (session/manager.py) - Conversation history
    └── LLMProvider (providers/) - LiteLLM-based API calls
    ↓
Response back through MessageBus → Channel
```

### Key Components

- **agent/loop.py**: Main processing loop. Receives messages, calls LLM, executes tools, returns responses. Contains `AgentLoop._register_default_tools()` for tool registration.

- **agent/context.py**: `ContextBuilder` assembles system prompts from:
  - Bootstrap files: `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`
  - Memory: `memory/MEMORY.md` and daily notes
  - Skills: Loaded from `skills/*/SKILL.md`

- **agent/tools/**: Tool implementations (filesystem, shell, web, spawn, message, cron). Each tool extends `Tool` base class with `name`, `description`, `parameters`, and `execute()`.

- **agent/subagent.py**: `SubagentManager` handles background task execution via the `spawn` tool.

- **providers/litellm_provider.py**: Unified LLM interface supporting OpenRouter, Anthropic, OpenAI, DeepSeek, Groq, Gemini, and local vLLM servers.

- **channels/**: Each channel (telegram.py, whatsapp.py, feishu.py) implements async message handling and converts to/from `InboundMessage`/`OutboundMessage`.

- **bridge/**: Node.js WhatsApp bridge using Baileys library. Communicates with Python via WebSocket.

### Skills System

Skills are markdown files with YAML frontmatter in `nanobot/skills/*/SKILL.md` or user workspace `~/.nanobot/skills/*/SKILL.md`. Skills can be:
- `alwaysLoad: true` - Included in every prompt
- On-demand - Agent reads via `read_file` tool when needed

### Configuration

Config file: `~/.nanobot/config.json`
- `providers`: API keys for LLM providers
- `agents.defaults.model`: Default model to use
- `channels`: Telegram/WhatsApp/Feishu settings
- `tools.web.search.apiKey`: Brave Search API key

### Adding New Tools

1. Create class extending `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute()`
3. Register in `AgentLoop._register_default_tools()`

### Adding New Skills

Create `nanobot/skills/{skill-name}/SKILL.md` with:
```yaml
---
name: skill-name
description: What this skill does
alwaysLoad: false
---

# Instructions for the agent...
```
