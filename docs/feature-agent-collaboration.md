# Agent Collaboration — Cross-Instance Message Bus

**Status:** Implemented and tested (PR ready)  
**Date:** 2026-05-24  
**Author:** Yiannis Sofologis  
**GitHub:** https://github.com/modelgrok/nanobot

---

## Overview

Nanobot can now run **multiple agent instances** that communicate with each
other over a shared message bus. Previously each agent was an island —
messages only flowed between a user and their assigned agent. Now agents
can delegate tasks, share context, and route responses to each other,
whether they run in the same process or on different machines.

Three backends are supported:

| Backend | Dependency | Delivery | Use Case |
|---------|-----------|----------|----------|
| **NATS** | `nats-py` | Pub/sub, persistent | Production multi-agent |
| **Redis** | `redis-py` | Pub/sub, fire-and-forget | Multi-agent with existing Redis |
| **Local** | none | `asyncio.Queue` | Single-agent (default) |

All backends share the same wire format, routing rules, and API — swapping
backends is a one-line config change.

---

## What Changed

### Files modified

| File | Δ lines | Change |
|------|---------|--------|
| `nanobot/bus/redis.py` | +237 −264 | Complete rewrite: Streams → pub/sub |
| `nanobot/bus/factory.py` | +12 −0 | New Redis constructor signature |
| `nanobot/config/schema.py` | +5 −0 | `channel_prefix` field added |

**Zero changes** to the agent loop, channel manager, CLI, gateway, or any
tool. The bus is a pure infrastructure layer swapped behind a stable
interface.

---

## Architecture

### Core Data Model

Two message types flow through the bus:

```
InboundMessage
├── channel      — source ("cli", "telegram", "bus", etc.)
├── sender_id    — opaque user/channel identifier
├── chat_id      — conversation identifier
├── content      — text payload
├── sender       — human-readable name or agent_id
├── session_key  — LLM session identifier
└── metadata     — routing info (target_agent, ttl, ...)

OutboundMessage
├── channel     — target channel
├── chat_id     — target conversation
├── content     — response text
├── reply_to    — optional message ID being replied to
└── metadata    — additional context
```

### Base MessageBus (`nanobot/bus/queue.py`)

The abstract base class owns three **in-process `asyncio.Queue`** instances:

```
MessageBus
├── inbound        — user CLI/input messages → agent loop
├── outbound       — agent responses → channel manager
└── agent_inbound  — messages FROM other agents → agent loop
```

Every backend (NATS, Redis, local) implements this same contract. The agent
loop and channel manager never know which backend is in use.

### Routing Rules

Cross-instance routing is driven by `metadata.target_agent`:

| target_agent | Behaviour |
|-------------|-----------|
| `None` or empty | Local only (same-instance inbound queue) |
| matches own `agent_id` | Local only (same-instance optimisation) |
| `"*"` | Broadcast — local + all remote agents |
| different `agent_id` | Network publish to that agent's subject/channel |

### Loop Prevention

Every cross-instance message includes `metadata.ttl` (hop counter). Each
agent decrements `ttl` before forwarding. When `ttl == 0`, the message is
dropped. Default initial value is `1` (single hop — no re-forwarding).

---

## Backend Implementations

### 1. NATS (`nanobot/bus/nats.py`)

**Production default.** Each agent subscribes to its own NATS subject:

```
nanobot.agent.{agent_id}
nanobot.agent.broadcast
```

The NATS server handles routing — publishing to
`nanobot.agent.bot-work` delivers directly to bot-work's subscriber.

Key properties:
- Automatic reconnection with `reconnect_time_wait=2s`
- Infinite retry on disconnect
- No consumer group management
- Subscriptions survive reconnects (NATS re-subscribes automatically)

### 2. Redis (`nanobot/bus/redis.py`)

**NATS-style pub/sub over Redis.** Each agent subscribes to two channels:

```
{channel_prefix}:{own_agent_id}    (e.g. nanobot:agent:bot-life)
{channel_prefix}:broadcast
```

Publishing to `nanobot:agent:bot-work` delivers to bot-work's subscriber
via Redis PUBLISH.

Key properties:
- Uses **two dedicated Redis connections** — one for publishing, one for
  the blocking SUBSCRIBE loop (required by redis-py)
- Background asyncio task (`_listen()`) reads from the pub/sub subscriber
  and feeds the local `agent_inbound` queue
- Fire-and-forget semantics — unsubscribed agents miss the message
- Wire format identical to NATS (same JSON field keys)

**Why pub/sub instead of Streams?**

The original implementation used Redis Streams with consumer groups
(XADD / XREADGROUP / XACK). This was replaced for several reasons:

| Aspect | Streams (old) | Pub/sub (new) |
|--------|--------------|----------------|
| Complexity | 325 lines, consumer groups, stream management | 301 lines, simpler |
| Persistence | Streams kept history needed trimming | No history, no management |
| Distribution | Consumer groups required complex routing | Direct channel delivery |
| NATS parity | Different semantics than NATS | Same semantics as NATS |
| Startup hang | Stream subscription bugs during testing | Clean async listener |

The pub/sub approach mirrors NATS exactly — same routing, same wire
format, same fire-and-forget semantics. Switching between NATS and Redis
is transparent to the agent.

### 3. Local / In-Process (`nanobot/bus/queue.py`)

Uses plain `asyncio.Queue` instances — zero network dependencies. This is
the safe default when no `bus` section is configured.

---

## Factory & Configuration

### Backend resolution (`nanobot/bus/factory.py`)

Priority chain:

```
1. config.bus.backend          (from config.json)
2. NANOBOT_BUS_BACKEND         (environment variable)
3. "local"                     (in-process, safe default)
```

### config.json format

```json
{
  "bus": {
    "backend": "nats",
    "agentId": "bot-life",
    "url": "nats://nats:4222",

    "subjectPrefix": "nanobot.agent",      # NATS only
    "channelPrefix": "nanobot:agent",      # Redis only
    "streamPrefix": "nanobot:bus",         # legacy, no-op
    "consumerGroup": "nanobot-consumers",  # legacy, no-op
    "readBlockMs": 2000                    # legacy, no-op
  }
}
```

Both **camelCase** and **snake_case** keys are accepted (Pydantic aliasing).

### Environment variable fallback

| Variable | Backend | Default |
|----------|---------|---------|
| `NANOBOT_BUS_BACKEND` | all | `"local"` |
| `NANOBOT_AGENT_ID` | all | `""` |
| `NANOBOT_BUS_URL` | nats, redis | varies by backend |
| `NANOBOT_BUS_SUBJECT_PREFIX` | nats | `"nanobot.agent"` |
| `NANOBOT_BUS_CHANNEL_PREFIX` | redis | `"nanobot:agent"` |

### Pydantic Config Schema (`nanobot/config/schema.py`)

```python
class BusConfig(Base):
    backend: Literal["local", "nats", "redis"] = "nats"
    url: str = ""
    agent_id: str = ""
    subject_prefix: str = "nanobot.agent"
    channel_prefix: str = "nanobot:agent"
    # legacy fields (no-op, backward-compatible):
    stream_prefix: str = "nanobot:bus"
    consumer_group: str = "nanobot-consumers"
    read_block_ms: int = 2000
```

The factory bridges between the Pydantic schema (loaded from config.json)
and the internal dataclass (`nanobot/bus/config.py`) using `getattr()` for
field access so either type works.

---

## Message Flow

### Inbound (user → agent)

```
User types "hello"
    │
    ▼
Channel creates InboundMessage
    │
    ▼
bus.publish_inbound(msg)
  ├── if target_agent is None or matches this agent:
  │     └── put on self.inbound queue
  └── if target_agent is set and != this agent:
        └── publish to network backend
              └── remote agent's listener picks it up
                    └── put on remote agent.agent_inbound queue
    │
    ▼
Agent loop: consume_inbound() → processes via LLM → responds
    │
    ▼
bus.publish_outbound(response) → channel manager delivers
```

### Cross-instance (agent → agent)

```
Agent (bot-life) decides to send to bot-work
    │
    ▼
Creates InboundMessage with metadata.target_agent = "bot-work"
    │
    ▼
bus.publish_agent_message(msg)
  └── publishes to NATS subject / Redis channel for bot-work
    │
    ▼
bot-work's subscription callback receives it
  └── deserialises → puts on agent_inbound queue
    │
    ▼
bot-work's agent loop: consume_agent_message() → processes → responds
    │
    ▼
Response delivered back to original channel via publish_outbound()
```

---

## Cross-Instance Messaging API

To send a message to another agent from within a skill or tool:

```python
from nanobot.bus.events import InboundMessage

msg = InboundMessage(
    channel="bus",
    sender_id="interagent",
    chat_id="interagent",
    content="Please summarise the latest news",
    sender=self.bus.agent_id,              # source agent
    session_key_override="interagent",
    metadata={
        "target_agent": "bot-work",        # destination agent
        "ttl": 1,                          # loop prevention
    },
)
await self.bus.publish_agent_message(msg)
```

To broadcast to all agents:

```python
metadata = {"target_agent": "*", "ttl": 1}
```

---

## Deployment — Example: Three Agents on NATS

```json
// config-bot-life.json
{"bus": {"backend": "nats", "agentId": "bot-life", "url": "nats://nats:4222"}}

// config-bot-work.json
{"bus": {"backend": "nats", "agentId": "bot-work", "url": "nats://nats:4222"}}

// config-bot-rnd.json
{"bus": {"backend": "nats", "agentId": "bot-rnd", "url": "nats://nats:4222"}}
```

```bash
# Start each agent independently
nanobot gateway --config config-bot-life.json
nanobot gateway --config config-bot-work.json
nanobot gateway --config config-bot-rnd.json
```

To switch to Redis, change only `backend` and `url`:

```json
{"bus": {"backend": "redis", "agentId": "bot-life", "url": "redis://localhost:6379/0"}}
```

---

## Wire Format

All network backends serialise `InboundMessage` as JSON with identical
field keys, making NATS and Redis wire-compatible:

```json
{
  "session_key": "interagent",
  "content": "Please summarise the latest news",
  "sender": "bot-life",
  "channel": "bus",
  "chat_id": "interagent",
  "sender_id": "interagent",
  "metadata": "{\"target_agent\": \"bot-work\", \"ttl\": 1}"
}
```

Field keys are defined as module-level constants in each backend file:

```
_FIELD_SESSION_KEY  = "session_key"
_FIELD_CONTENT      = "content"
_FIELD_SENDER       = "sender"
_FIELD_METADATA     = "metadata"
_FIELD_CHANNEL      = "channel"
_FIELD_CHAT_ID      = "chat_id"
_FIELD_SENDER_ID    = "sender_id"
```

---

## Package Structure

```
nanobot/bus/
├── __init__.py     — re-exports: BusConfig, InboundMessage, OutboundMessage,
│                     MessageBus, create_bus
├── config.py       — BusConfig dataclass + BackendType
├── events.py       — InboundMessage, OutboundMessage dataclasses
├── factory.py      — create_bus() factory with backend resolution
├── queue.py        — MessageBus abstract base + local in-process impl
├── nats.py         — NATSMessageBus (NATS pub/sub)
├── redis.py        — RedisMessageBus (Redis pub/sub)
└── zmq.py          — ZMQMessageBus (ZeroMQ PUB/SUB, peer-to-peer)
```

---

## Adding a New Backend

1. Create `nanobot/bus/{name}.py`
2. Subclass `MessageBus`, implement all abstract methods:
   - `start()`, `stop()`
   - `publish_inbound()`, `publish_outbound()`, `publish_agent_message()`
   - `consume_inbound()`, `consume_outbound()`, `consume_agent_message()`
3. Use the same JSON wire format (same field keys) for compatibility
4. Add the backend string to `BackendType` in `bus/config.py`
5. Add the case to `create_bus()` in `bus/factory.py`
6. No changes needed in the agent loop, channel manager, or any tool

---

## Test Results

### Single-agent local (in-process)

| Scenario | Result |
|----------|--------|
| Inbound user message → local queue | Pass |
| Outbound response → local queue | Pass |
| Cross-instance with no target_agent | Local only (correct) |

### Three-agent Redis pub/sub round-trip

| Scenario | Result |
|----------|--------|
| bot-life → bot-work point-to-point | Pass (delivered in <2ms) |
| bot-life → bot-rnd point-to-point | Pass |
| bot-rnd → broadcast (all three receive) | Pass |
| Outbound local queue | Pass |
| Stop/start lifecycle | Pass |

### NATS regression

| Scenario | Result |
|----------|--------|
| NATS connect, start, stop | Pass |
| Cross-instance publish | Pass (from previous session) |

---

## Related Discussions

- **PR:** https://github.com/modelgrok/nanobot/pull/... (link after submission)
- **Design doc:** `artifacts/agent_messaging_spec.md` in workspace
- **User task:** `user-tasks/agent_collaboration/USER-TASK.md`