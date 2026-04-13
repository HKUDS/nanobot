# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (pytest with asyncio_mode = "auto")
pytest                           # all tests
pytest tests/test_telegram_channel.py  # single test

# Lint and format (line length: 100, target: Python 3.11+)
ruff check nanobot/
ruff format nanobot/
```

### CLI

```bash
nanobot onboard                  # Initialize config & workspace at ~/.nanobot/
nanobot agent -m "..."           # Chat with the agent
nanobot agent                    # Interactive chat mode
nanobot gateway                  # Start the gateway (connects to enabled channels)
nanobot status                   # Show status
nanobot plugins list             # List available channel plugins
```

### Desktop App (Tauri + React + Tailwind v4)

Located in `desktop/`. Requires Node.js ≥18 and Bun ≥1.0.

```bash
cd desktop
npm install / bun install        # Install dependencies
npm run dev / bun run dev        # Dev server (Vite)
npm run tauri:dev                # Tauri dev mode
npm run build / bun run build    # Build for production
npm run tauri:build              # Build Tauri app
```

### WhatsApp Bridge (Node.js + TypeScript)

Located in `bridge/`. Requires Node.js ≥20.

```bash
cd bridge
npm install
npm run build                    # Compile TypeScript
npm run start                    # Start bridge (scan QR)
```

## Architecture Overview

nanobot is an ultra-lightweight personal AI assistant framework. The core design follows a message-bus architecture:

**Core Flow:**
1. Channels (Telegram, Discord, etc.) receive messages → publish to `MessageBus`
2. `AgentLoop` subscribes to the bus → builds context → calls LLM → executes tools
3. Responses flow back through channels to users

**Key Components:**

| Module | Role |
|--------|------|
| `nanobot/agent/loop.py` | Core agent processing: LLM ↔ tool execution loop |
| `nanobot/agent/context.py` | Builds prompts from history, memory, skills, MCP tools |
| `nanobot/agent/memory.py` | Token-based memory consolidation (not sliding window) |
| `nanobot/agent/tools/` | Built-in tools (shell, filesystem, web, spawn, cron, MCP) |
| `nanobot/channels/` | Chat platform integrations (Telegram, Discord, Feishu, etc.) |
| `nanobot/bus/` | Message bus (`MessageBus`, `InboundMessage`, `OutboundMessage`) |
| `nanobot/providers/` | LLM provider abstraction (LiteLLM-based, plus direct/custom) |
| `nanobot/config/` | Pydantic-based config schema (`~/.nanobot/config.json`) |
| `nanobot/session/` | Session management (thread-scoped conversations) |
| `nanobot/cron/` | Scheduled task service (reads `~/.nanobot/cron/*.json`) |
| `nanobot/heartbeat/` | Proactive wake-up (reads `~/.nanobot/workspace/HEARTBEAT.md`) |
| `nanobot/gateway/api.py` | HTTP/WebSocket API for desktop/web clients |
| `nanobot/cli/commands.py` | Typer-based CLI commands |

**Tool Execution Model:**
- Tools are registered in `ToolRegistry`
- MCP tools are auto-discovered and wrapped with `mcp_` prefix
- Each tool has a JSON schema for LLM calling
- Subagent (`spawn` tool) runs background tasks in same process

## Adding New Features

### Add a New LLM Provider

Two steps only — registry drives everything:

**Step 1:** Add `ProviderSpec` to `PROVIDERS` in `nanobot/providers/registry.py`:
```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    env_key="MYPROVIDER_API_KEY",
    litellm_prefix="myprovider",
)
```

**Step 2:** Add field to `ProvidersConfig` in `nanobot/config/schema.py`:
```python
class ProvidersConfig(Base):
    ...
    myprovider: ProviderConfig = Field(default_factory=ProviderConfig)
```

That's it. Env vars, model prefixing, config matching, and `nanobot status` display all derive from these entries.

### Add a New Channel

Built-in: Add module to `nanobot/channels/{name}.py` extending `BaseChannel`.

Plugin (recommended): Create separate package with entry point:
```toml
[project.entry-points."nanobot.channels"]
mychannel = "nanobot_channel_mychannel:MyChannel"
```

See `docs/CHANNEL_PLUGIN_GUIDE.md` for full reference. Key points:
- `async start()` must block forever — if it returns, channel is dead
- Call `self._handle_message(sender_id, chat_id, content, media)` to publish to bus
- Implement `async send(msg: OutboundMessage)` to deliver responses

### Add a New Built-in Tool

1. Create class in `nanobot/agent/tools/` extending `BaseTool`
2. Register in `AgentLoop.__init__()` via `self.tools.register()`
3. Add JSON schema in `to_schema()` method for LLM calling

### Add a New Skill

Skills are markdown + shell scripts in `nanobot/skills/{name}/`. The agent reads them at runtime and executes the embedded shell commands.

## Configuration

Config file: `~/.nanobot/config.json` (Pydantic schema in `nanobot/config/schema.py`)

**Key sections:**
- `providers.{name}`: LLM provider credentials (openrouter, anthropic, groq, etc.)
- `agents.defaults`: Model, workspace, temperature, context window
- `channels.{name}`: Per-channel config with `enabled` + `allowFrom`
- `tools.web.search`: Web search provider (brave, tavily, jina, searxng, duckduckgo)
- `tools.mcpServers`: MCP servers (stdio or HTTP transport)
- `tools.restrictToWorkspace`: Sandbox all file/shell tools to workspace directory

**Multiple Instances:** Use `--config` to point to different config files. Runtime data (cron, media) derives from config directory.

## Important Patterns

**Channel Authorization:** Empty `allowFrom` now denies all (since v0.1.4.post4). Use `["*"]` to allow all users.

**Session Isolation:** Sessions are keyed by `{channel}:{chat_id}`. Override with `session_key_override` metadata for thread-scoped sessions.

**Memory Consolidation:** Token-based, not sliding window. See `nanobot/agent/memory.py` for consolidation logic.

**MCP Tools:** Auto-discovered on gateway start. Use `enabledTools` to filter subset. Timeout default is 30s per call.

**Provider Retry:** Shared retry logic in `nanobot/providers/base.py`. All providers inherit retry behavior.

**WebSocket vs HTTP:** Feishu, QQ, DingTalk, Slack, Wecom use WebSocket long connections — no public IP required. Discord uses HTTP polling.

## Testing

- Use `pytest` with `asyncio_mode = "auto"` (configured in `pyproject.toml`)
- Tests located in `tests/` directory
- Mock external APIs (channels, providers) in tests
- Each test file focuses on a single component

## Branching Strategy

- `main`: Stable releases (production-ready)
- `nightly`: Experimental features (may have bugs/breaking changes)

New features → `nightly`. Bug fixes → `main`. Stable features from `nightly` are cherry-picked to `main`.

## Desktop App Notes

The `desktop/` directory contains a Tauri v2 + React 18 + Tailwind v4 + shadcn/ui application. It communicates with the Python gateway via WebSocket (`ws://localhost:18790/api/chat`). The desktop app is a separate frontend that connects to the running `nanobot gateway`.

## WhatsApp Bridge Notes

The `bridge/` directory contains a Node.js/TypeScript bridge using `@whiskeysockets/baileys` for WhatsApp integration. It communicates with the Python gateway via WebSocket. After upgrading nanobot, rebuild the bridge with `rm -rf ~/.nanobot/bridge && nanobot channels login`.
