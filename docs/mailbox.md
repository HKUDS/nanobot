# Mailbox Channel — Inter-Agent Communication

The mailbox channel enables multiple independent nanobot agent instances to discover and communicate with each other via a file-system-based mailbox system. It is a built-in channel plugin — no external dependencies, no modifications to existing code.

## How It Works

Each agent runs its own `nanobot gateway` process with the mailbox channel enabled. Messages are exchanged through files on the local filesystem, making the system simple, debuggable, and side-effect-free.

```
Agent A (researcher)                    Agent B (coder)
  LLM calls MessageTool(                  │
    channel="mailbox",                    │
    chat_id="coder",                      │
    content="write sort"                  │
  )                                       │
      → OutboundMessage                   │
      → MailboxChannel.send()             │
      → writes to ~/.nanobot/mailboxes/coder/inbox/
                                          │
                                          ← poll reads inbox
                                          ← InboundMessage → AgentLoop
                                          ← LLM processes task
                                          ←
      ← MailboxChannel.send()             ← LLM calls MessageTool(
      ← writes to researcher/inbox/           channel="mailbox",
      ← poll reads inbox                      chat_id="researcher",
      ← routes to user via Feishu             content="done"
                                            )
```

The LLM uses the **existing** `MessageTool` with `channel="mailbox"` and `chat_id="<target_agent_id>"` to send messages. No new tools are needed.

## Features

- **Peer-to-peer** — fully connected topology, any agent can message any other
- **Asynchronous** — messages are queued in the recipient's inbox, processed on next poll
- **Callback routing** — task results route back to the original user session (e.g., Feishu)
- **Anti-loop protection** — TTL hop count + circular trace detection
- **Access control** — `allowFrom` restricts which agents can send messages
- **Agent discovery** — agents register in a shared registry with descriptions and capabilities
- **Zero side effects** — only new files, no modifications to existing code

## Quick Start

### 1. Configure Agent A (researcher)

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "...",
      "appSecret": "..."
    },
    "mailbox": {
      "enabled": true,
      "agentId": "researcher",
      "description": "Research agent — web search and analysis",
      "capabilities": ["web_search", "code_analysis"],
      "allowFrom": ["*"],
      "pollInterval": 5,
      "mailboxesRoot": "~/.nanobot/mailboxes"
    }
  }
}
```

### 2. Configure Agent B (coder)

```json
{
  "channels": {
    "mailbox": {
      "enabled": true,
      "agentId": "coder",
      "description": "Code writing agent",
      "capabilities": ["code_write", "test_run"],
      "allowFrom": ["researcher"],
      "pollInterval": 5,
      "mailboxesRoot": "~/.nanobot/mailboxes"
    }
  }
}
```

### 3. Start both agents

```bash
# Terminal 1
nanobot gateway -c researcher-config.json

# Terminal 2
nanobot gateway -c coder-config.json
```

Both agents register in `~/.nanobot/mailboxes/_registry.json` and can discover each other.

## Configuration Reference

All fields go under `channels.mailbox` in `config.json`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the mailbox channel. |
| `agentId` | string | `""` | **Required.** Unique identifier for this agent. Used as mailbox address. |
| `description` | string | `""` | Human-readable description for agent discovery. |
| `capabilities` | list of string | `[]` | List of capabilities this agent offers (for discovery). |
| `allowFrom` | list of string | `["*"]` | Allowed sender agent IDs. `"*"` allows all. `[]` denies all. |
| `maxConcurrentTasks` | int | `3` | Maximum concurrent tasks this agent accepts. |
| `pollInterval` | float | `5.0` | Inbox polling interval in seconds. |
| `mailboxesRoot` | string | `"~/.nanobot/mailboxes"` | Root directory for mailbox files. All agents must share the same path. |

## File Structure

```
~/.nanobot/mailboxes/
├── _registry.json                  # Agent cards (discovery)
├── researcher/
│   ├── inbox/                      # Pending messages
│   │   └── 1745659200_coder_a1b2c3d4.msg.json
│   └── processed/                  # Archived messages
└── coder/
    ├── inbox/
    └── processed/
```

## Anti-Loop Protection

Two mechanisms prevent infinite agent-to-agent conversations:

1. **TTL** (Time-to-Live) — Decremented on each relay. Default is 3 (max 3 hops: A→B→C→D). At 0, the agent cannot delegate further.

2. **Trace** — List of agent IDs the message has passed through. Rejects forwarding to any agent already in the trace.

| Scenario | Protection |
|----------|-----------|
| A↔B mutual ping | Trace: B sees A in trace, rejects |
| A→B→C→A cycle | Trace: C sees A in trace, rejects |
| A→B→C→D→... infinite chain | TTL: reaches 0, stops |

## Callback Routing

When a user sends a message through Feishu to Agent A, and Agent A delegates a task to Agent B, the task carries a `callback` field:

```json
{
  "callback": {
    "channel": "feishu",
    "chat_id": "user_123",
    "session_id": "feishu:user_123"
  }
}
```

When Agent B responds with the callback, Agent A's MailboxChannel routes the response back to the original Feishu conversation. The user never interacts with the mailbox directly — it's invisible infrastructure.

## Agent States

| State | Accept New Tasks? | Description |
|-------|-------------------|-------------|
| `idle` | Yes | Available, accepts immediately |
| `busy` | If quota allows | `current_tasks` < `maxConcurrentTasks` |
| `offline` | Messages queue | Messages stay in inbox, processed when agent comes online |

State transitions:
- Startup → `idle`
- Receive task + accept → `busy`
- All tasks completed → `idle`
- Heartbeat timeout → `offline` (other agents detect via registry)

## Message Format

Messages are JSON files in the inbox:

```json
{
  "id": "msg_1745659200_researcher",
  "from": "researcher",
  "to": "coder",
  "timestamp": "2026-04-26T10:00:00Z",
  "type": "task",
  "ttl": 2,
  "trace": ["researcher"],
  "task": {
    "id": "original_task_id",
    "state": "pending"
  },
  "content": {
    "parts": [
      {"type": "text", "text": "Please write a sort function"}
    ]
  },
  "callback": {
    "channel": "feishu",
    "chat_id": "user_123",
    "session_id": "feishu:user_123"
  }
}
```

## Common Patterns

### Two agents on the same machine

Both agents share the same `mailboxesRoot`:

```json
"mailboxesRoot": "~/.nanobot/mailboxes"
```

### Restrict access to specific agents

```json
"allowFrom": ["researcher", "writer"]
```

### Faster polling for low-latency tasks

```json
"pollInterval": 1
```
