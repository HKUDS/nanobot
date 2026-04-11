# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI agent framework written in Python. It provides a minimal implementation of core agent functionality including LLM integration, tool use, memory management, and multi-channel chat platform support.

## Development Commands

### Setup
```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Or install with specific extras
pip install -e ".[api,matrix,weixin,wecom]"
```

### Testing
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=nanobot --cov-report=term-missing

# Run a specific test file
pytest tests/tools/test_filesystem_tools.py

# Run a specific test
pytest tests/tools/test_filesystem_tools.py::test_read_file
```

### Linting and Formatting
```bash
# Check code style
ruff check nanobot/

# Fix auto-fixable issues
ruff check --fix nanobot/

# Format code
ruff format nanobot/
```

### Running the Application
```bash
# Initialize config
nanobot onboard

# Start interactive CLI mode
nanobot agent

# Start gateway (for chat channels)
nanobot gateway

# Check status
nanobot status
```

### Docker
```bash
# Build and run via docker-compose
docker compose run --rm nanobot-cli onboard
docker compose up -d nanobot-gateway

# Build image directly
docker build -t nanobot .
```

## High-Level Architecture

### Core Components

**Agent Loop** (`nanobot/agent/loop.py`): The central processing engine that orchestrates LLM interactions and tool execution. Uses an event-driven architecture with hooks for extensibility.

**Message Bus** (`nanobot/bus/`): Decouples channels from the agent. Channels publish inbound messages to the bus; the agent publishes outbound responses.

**Session Management** (`nanobot/session/`): Maintains conversation state. Sessions are keyed by `channel:chat_id` (or unified when `unified_session` is enabled).

**Tool System** (`nanobot/agent/tools/`):
- Registry pattern for tool discovery
- Built-in tools: filesystem, shell (exec), web search/fetch, cron, spawn
- MCP support for external tool servers
- Tools are async and return structured results

**Provider System** (`nanobot/providers/`):
- Registry-based provider discovery (`nanobot/providers/registry.py`)
- Supports OpenAI-compatible APIs, Anthropic, Azure OpenAI, OAuth providers
- Auto-detection based on API key prefixes and base URLs
- To add a provider: add `ProviderSpec` to registry + field to `ProvidersConfig`

**Channels** (`nanobot/channels/`):
- Base class defines the interface: `start()`, `send()`, `transcribe_audio()`
- Each channel is a long-running async task
- Channel manager coordinates multiple channels
- Supports plugins via entry points

**Memory System** (`nanobot/agent/memory.py`):
- Layered: working context → summarized history (`memory/history.jsonl`) → long-term (`SOUL.md`, `USER.md`)
- Dream runs on schedule to consolidate memories
- Git-based versioning for memory changes

### Data Flow

1. **Inbound**: Channel receives message → publishes to bus → session manager routes to appropriate session
2. **Processing**: Agent loop builds context → calls LLM → executes tools → streams responses
3. **Outbound**: Responses published to bus → channel manager routes to originating channel

### Configuration

- Config file: `~/.nanobot/config.json` (or via `--config`)
- Schema defined in `nanobot/config/schema.py` using Pydantic
- Supports environment variable interpolation: `${VAR_NAME}`
- Multiple instances supported via separate config files

### Key Design Patterns

- **Async/await throughout**: All I/O is async using `asyncio`
- **Hook system**: `AgentHook` allows extending behavior without modifying core
- **Registry pattern**: Providers, tools, and channels use registries for discovery
- **Pydantic models**: Configuration and data validation use Pydantic
- **Sandboxing**: Shell execution can use bubblewrap (`bwrap`) for isolation

## Testing Guidelines

- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock external I/O; test business logic in isolation
- Security tests are in `tests/tools/test_exec_security.py` and `tests/security/`
- Coverage configured in `pyproject.toml`

## Branch Strategy

- `main`: Stable releases, bug fixes, docs
- `nightly`: New features, refactoring, experimental changes
- Features are cherry-picked from `nightly` to `main` when stable

## Code Style

- Line length: 100 characters
- Python 3.11+ required
- Ruff for linting/formatting (rules: E, F, I, N, W; E501 ignored)
- Prefer simple, readable code over clever abstractions
