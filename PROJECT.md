# nanobot — Project Analysis

## What It Is

**nanobot** (`nanobot-ai` on PyPI) is an ultra-lightweight (~4k lines) personal AI assistant framework.
It provides a pluggable channel-based architecture so one agent can chat through Telegram, Slack, Discord, WhatsApp, and more — all simultaneously.

---

## Architecture

```
User (Telegram/Slack/etc.)
        │
        ▼
  ┌─────────────┐      InboundMessage     ┌─────────────┐
  │  Channel    │ ──────────────────────► │  MessageBus │
  │ (per platform) ◄──────────────────── │  (asyncio Q)│
  └─────────────┘      OutboundMessage    └──────┬──────┘
                                                 │ consumes
                                                 ▼
                                         ┌───────────────┐
                                         │  AgentLoop    │
                                         │  (LLM + tools)│
                                         └───────────────┘
```

### Core Components

| Component | Path | Role |
|-----------|------|------|
| `AgentLoop` | `nanobot/agent/loop.py` | Core LLM ↔ tool loop; reads from bus, writes responses back |
| `MessageBus` | `nanobot/bus/queue.py` | Two `asyncio.Queue`s: inbound (user→agent) + outbound (agent→user) |
| `BaseChannel` | `nanobot/channels/base.py` | Abstract class all channels implement |
| `ChannelManager` | `nanobot/channels/manager.py` | Starts/stops channels, dispatches outbound messages |
| `ContextBuilder` | `nanobot/agent/context.py` | Builds LLM message history |
| `MemoryStore` | `nanobot/agent/memory.py` | Persistent memory with consolidation |
| `SessionManager` | `nanobot/session/manager.py` | Per-session conversation history |
| `CronService` | `nanobot/cron/service.py` | Scheduled tasks |
| `HeartbeatService` | `nanobot/heartbeat/service.py` | Periodic background tasks |

### Channel Contract (BaseChannel ABC)

Each channel must implement three methods:
```python
async def start(self) -> None:   # Connect & listen for messages
async def stop(self) -> None:    # Clean up
async def send(self, msg: OutboundMessage) -> None:  # Deliver a response
```

Channels call `self._handle_message(...)` which creates an `InboundMessage` and pushes it to `bus.publish_inbound()`.

### Message Flow

1. Channel receives user message → calls `_handle_message()` → `InboundMessage` on bus
2. `AgentLoop.run()` pulls from `bus.consume_inbound()`
3. Builds prompt from history + current message → calls LLM
4. Executes tool calls (filesystem, shell, web search, etc.) in a loop
5. Publishes `OutboundMessage` to `bus.publish_outbound()`
6. `ChannelManager._dispatch_outbound()` routes to the right channel's `send()`

### Progress / Streaming

The agent emits two types of outbound messages:
- **Progress** (`metadata["_progress"] = True`): intermediate tool hints or partial text mid-turn
- **Final** (no `_progress` flag): the completed response

Both flow through the same `bus.outbound` queue.

---

## Key Design Patterns

- **Session key**: `"{channel}:{chat_id}"` — isolates conversation history per chat
- **Config**: Pydantic `BaseSettings` with camelCase JSON (`~/.nanobot/config.json`)
- **Provider abstraction**: LiteLLM-backed, supports OpenRouter, Anthropic, OpenAI, DeepSeek, etc.
- **Tools**: Registered in `ToolRegistry`; built-ins include filesystem r/w, shell exec, web search, MCP
- **Skills**: Markdown files loaded into agent system prompt
- **CLI entry**: `nanobot agent` (direct), `nanobot gateway` (all channels)

---

## Existing Channels

| Channel | Transport | Auth |
|---------|-----------|------|
| Telegram | Long-polling | Bot token |
| Discord | WebSocket | Bot token |
| Slack | Socket Mode | Bot + App token |
| WhatsApp | Node.js bridge + WS | QR scan |
| Feishu | WebSocket | App ID/Secret |
| DingTalk | Stream mode | Client ID/Secret |
| Email | IMAP/SMTP | Credentials |
| QQ | botpy SDK + WS | App ID/Secret |
| Matrix | Matrix Sync API | Access token |
| Mochat | Socket.IO | Claw token |

---

## Dependencies (Relevant)

- `aiohttp` — available transitively via `python-socketio`
- `websockets` — explicit dep
- `httpx` — explicit dep (HTTP client)
- `litellm` — LLM abstraction layer
- `pydantic` — config/schema validation
- `rich` + `typer` — CLI

No web framework (FastAPI/aiohttp) is a direct dependency yet.

---

## Entry Points

| Command | What it does |
|---------|-------------|
| `nanobot onboard` | Initialize config + workspace |
| `nanobot agent -m "..."` | Single-shot CLI chat |
| `nanobot agent` | Interactive CLI chat |
| `nanobot gateway` | Start all enabled channels |

---

## Configuration (`~/.nanobot/config.json`)

```json
{
  "providers": { "openrouter": { "apiKey": "sk-or-..." } },
  "agents": { "defaults": { "model": "anthropic/claude-opus-4-5" } },
  "channels": { "<channel>": { "enabled": true, ... } }
}
```

---

## Extension Points

Adding a new channel takes **3 steps**:
1. Create `nanobot/channels/<name>.py` with `class XChannel(BaseChannel)`
2. Add `<name>Config` to `nanobot/config/schema.py` → `ChannelsConfig`
3. Register it in `nanobot/channels/manager.py`

That's exactly the pattern we'll follow for the web chat channel.
