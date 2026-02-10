# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- **Install (Dev)**: `pip install -e .` or `uv pip install -e .`
- **Run Agent**: `nanobot agent -m "Your message"`
- **Run Gateway**: `nanobot gateway`
- **Interactive Mode**: `nanobot agent`
- **Check Status**: `nanobot status`
- **Run Tests**: `pytest`
- **Run Single Test**: `pytest tests/path/to/test.py`
- **Lint**: `ruff check .`
- **Format**: `ruff format .`
- **Build Docker**: `docker build -t nanobot .`

## Architecture

Nanobot is a lightweight personal AI assistant framework (~4k lines of core code).

- **Core (`nanobot/agent/`)**:
  - `loop.py`: Main agent loop handling LLM interaction and tool execution.
  - `context.py`: Manages conversation context and prompt building.
  - `memory.py`: Handles persistent memory.
  - `tools/`: Built-in tools.
  - `subagent.py`: Handles background task execution.

- **Integrations**:
  - **Providers (`nanobot/providers/`)**: LLM backend integrations. `registry.py` is the source of truth.
  - **Channels (`nanobot/channels/`)**: Chat platform integrations (Telegram, Discord, Feishu, WhatsApp, etc.).
  - **Skills (`nanobot/skills/`)**: Bundled capabilities loaded dynamically.

- **Infrastructure**:
  - **Bus (`nanobot/bus/`)**: Internal message routing.
  - **Config (`nanobot/config/`)**: Pydantic-based configuration management.
  - **CLI (`nanobot/cli/`)**: Command-line interface entry points using `typer`.
  - **Bridge (`bridge/`)**: Node.js bridge for WhatsApp integration.

## Development Patterns

- **Adding Providers**:
  1. Add a `ProviderSpec` to `nanobot/providers/registry.py`.
  2. Add a field to `ProvidersConfig` in `nanobot/config/schema.py`.
- **Adding Channels**:
  1. Inherit from `nanobot.channels.base.BaseChannel`.
  2. Implement `start()` (listener), `stop()` (cleanup), and `send()` (outbound).
  3. Use `_handle_message()` to forward platform messages to the internal bus.
- **Configuration**: User config defaults to `~/.nanobot/config.json`.
- **Testing**: `pytest` is configured with `asyncio_mode = auto`.
