# Multi-Agent Mailbox Communication Design

## Overview

Design a simple, zero-side-effect mechanism for multiple independent nanobot agent instances to communicate with each other. The mechanism uses a file-system-based mailbox system implemented as a standard nanobot channel plugin, requiring no modifications to existing code.

## Goals

- Multiple independent agent processes can discover and communicate with each other
- Peer-to-peer (fully connected) topology
- Asynchronous event-driven messaging
- "Boss experience": agents auto-delegate, auto-report progress, user only interacts through their normal channel (e.g., Feishu)
- Zero side effects: only new files added, no modifications to existing code
- Incorporate concepts from Google's A2A protocol (Agent Cards, Task lifecycle, Message Parts)

## Architecture

### Storage: File-System Mailbox

```
~/.nanobot/mailboxes/
├── _registry.json                  # Agent Cards (discovery)
├── researcher/
│   ├── inbox/                      # Pending messages
│   │   └── 1745659200_coder.msg.json
│   └── processed/                  # Archived messages
│       └── 1745659000_coder.msg.json
└── coder/
    ├── inbox/
    └── processed/
```

Global path `~/.nanobot/mailboxes/` is used because different agents may have different working directories.

### Message File Naming

`{unix_timestamp}_{from_agent_id}.msg.json`

Atomic writes: write to `.tmp` file first, then `os.rename()` to prevent reading half-written messages.

### Agent Discovery (A2A Agent Card)

Each agent registers itself in `_registry.json` on startup and updates `last_heartbeat` on every poll cycle.

The registry contains two types of data:
- **Agent identity** (`description`, `capabilities`) — configured by the user in `channels.mailbox` config section. Optional; if not set, other agents can only see `agent_id` and `status`.
- **Runtime state** (`status`, `current_tasks`, `last_heartbeat`) — computed automatically by the mailbox channel.

```json
{
  "researcher": {
    "agent_id": "researcher",
    "description": "负责信息检索和分析的 agent",
    "capabilities": ["web_search", "code_analysis", "summarization"],
    "status": "idle",
    "allow_from": ["coder", "writer"],
    "max_concurrent_tasks": 3,
    "current_tasks": ["msg_1745659200_coder"],
    "registered_at": "2026-04-26T10:00:00Z",
    "last_heartbeat": "2026-04-26T10:05:00Z"
  },
  "coder": {
    "agent_id": "coder",
    "description": "负责代码编写和修改的 agent",
    "capabilities": ["code_write", "test_run", "review"],
    "status": "idle",
    "allow_from": ["*"],
    "max_concurrent_tasks": 3,
    "current_tasks": [],
    "registered_at": "2026-04-26T10:00:30Z",
    "last_heartbeat": "2026-04-26T10:05:30Z"
  }
}
```

### Agent States

| State | Accept New Tasks? | Description |
|-------|-------------------|-------------|
| `idle` | Yes | Available, accepts immediately |
| `busy` | If quota allows | `current_tasks` < `max_concurrent_tasks` then queue, otherwise reject |
| `offline` | Messages queue | Messages stay in inbox, processed when agent comes online |

State transitions:
- Startup → `idle`
- Receive task + accept → `busy`
- All tasks completed → `idle`
- Heartbeat timeout → `offline`

## Communication Protocol

### Message Types

1. **message** — Instant notification, Q&A, chat
2. **task** — Work request requiring execution and result return
3. **task_update** — Status update for a previously sent task

### Task Lifecycle (A2A Task Concept)

```
pending → accepted → working → completed
                  \→ rejected
                  \→ failed
```

### Message Format

```json
{
  "id": "msg_1745659200_researcher",
  "from": "researcher",
  "to": "coder",
  "timestamp": "2026-04-26T10:00:00Z",
  "type": "task | message | task_update",
  "ttl": 3,
  "trace": ["researcher"],
  "task": {
    "id": "original_task_id",
    "state": "pending | accepted | working | completed | failed | rejected",
    "deadline": "2026-04-26T11:00:00Z"
  },
  "content": {
    "parts": [
      {"type": "text", "text": "..."},
      {"type": "data", "data": {}},
      {"type": "file", "path": "/path/to/file"}
    ]
  },
  "callback": {
    "session_id": "feishu:user_123",
    "channel": "feishu"
  },
  "reply_to": "replied_message_id | null",
  "metadata": {}
}
```

Fields:
- `ttl` — Time-to-live hop count. Decremented on each relay. Default 3. At 0, agent must handle itself, cannot delegate.
- `trace` — List of agent_ids this message has passed through. Prevents circular routing.
- `task` — Present for `task` and `task_update` types. Contains lifecycle state and optional deadline.
- `content.parts` — Structured content (A2A Message Parts concept). Supports text, data, and file types.
- `callback` — Original session info from the initiating channel. Carried through the task lifecycle so results route back to the correct user conversation.

### Task Acceptance Criteria

All conditions must be met for an agent to accept a task:
1. Sender is in `allow_from` list (`"*"` = accept all)
2. `current_tasks` count < `max_concurrent_tasks`
3. `deadline` has not expired (if present)
4. LLM judges it has the capability to complete the task

Decision outcomes:
- Accept → reply `task_update {state: "accepted"}`, add to `current_tasks`
- Reject → reply `task_update {state: "rejected"}` with reason

### Anti-Loop Mechanism

Two fields prevent infinite agent-to-agent conversations:

1. **TTL**: Decremented on each relay. At 0, no further delegation allowed. Default = 3 (max 3 hops: A→B→C→D).
2. **Trace**: Append agent_id on each relay. Reject forwarding to any agent already in trace.

| Scenario | Protection |
|----------|-----------|
| A↔B mutual ping | Trace: B sees A in trace, rejects |
| A→B→C→A cycle | Trace: C sees A in trace, rejects |
| A→B→C→D→... infinite chain | TTL: reaches 0, stops |

### User Experience: End-to-End Flow

The user never interacts with mailbox directly. They communicate through their normal channel (Feishu, WeChat, etc.). The mailbox is invisible infrastructure.

```
User (Feishu)           Agent A (researcher)       Agent B (coder)
│                       │                          │
│ "帮我写排序函数"        │                          │
│ ──────────────────→   │                          │
│                       │ LLM decides to delegate  │
│                       │                          │
│ "我让 coder 去处理，    │                          │
│  完成后通知你"          │                          │
│ ←──────────────────   │                          │
│                       │                          │
│       ...time passes...│                          │
│                       │                          │
│                       │ task {                    │
│                       │   callback: {             │
│                       │     session_id: "feishu:user_123",
│                       │     channel: "feishu"     │
│                       │   }                       │
│                       │ }                         │
│                       │ ──────────────────────→   │
│                       │                          │ B processes...
│                       │                          │
│                       │ task_update {completed}   │
│                       │ ←──────────────────────   │
│                       │                          │
│ MailboxChannel polls task_update                  │
│ Routes to session "feishu:user_123"               │
│ LLM sees result in original conversation context  │
│                       │                          │
│ "排序函数已完成：        │                          │
│  sort_by_mtime()..."  │                          │
│ ←──────────────────   │                          │
```

The `callback` field carries the original channel session info through the entire task lifecycle. When the task_update arrives at Agent A's mailbox, the MailboxChannel restores the original `session_id` and `channel`, so the AgentLoop processes it in the correct conversation context and the LLM naturally responds to the user via Feishu.

### Error Scenarios

| Scenario | Handling |
|----------|----------|
| Target agent offline | Messages queue in inbox; processed when agent comes online |
| Heartbeat timeout | Registry marks agent `offline`; visible to other agents on next registry read |
| Agent crash during task | No `completed`/`failed` sent; sender can use `deadline` to detect timeout |
| Task rejected | Sender receives `rejected` with reason; decides next action |
| Task deadline expired | Receiver checks deadline on processing; rejects if expired |
| allow_from mismatch | Receiver discards message; optionally replies `rejected` with "unauthorized" |
| Registry concurrent write | Atomic writes (.tmp → rename); each agent only writes its own entry |

## Implementation

### New Components

| Component | Type | Modifies Existing Code |
|-----------|------|----------------------|
| `MailboxManager` | New file (`nanobot/channels/mailbox_manager.py`) | No |
| `MailboxChannel` | New file (`nanobot/channels/mailbox.py`) | No |
| `MailboxConfig` | Pydantic model inside mailbox.py | No |
| Config section `channels.mailbox` | User config.json | No (additive) |

### MailboxManager

Low-level file operations with no nanobot dependencies:

```python
class MailboxManager:
    def __init__(self, mailboxes_root: Path): ...

    def register(self, agent_id: str, card: dict) -> None:
        """Atomic write to registry (.tmp → rename)"""

    def heartbeat(self, agent_id: str) -> None:
        """Update last_heartbeat in registry"""

    def update_status(self, agent_id: str, status: str, current_tasks: list[str] | None = None) -> None:
        """Update agent status and current task list"""

    def send(self, from_id: str, to_id: str, msg: dict) -> None:
        """Atomic write to to_id/inbox/{timestamp}_{from_id}.msg.json"""

    def poll(self, agent_id: str) -> list[dict]:
        """Scan inbox/, return new messages sorted by timestamp"""

    def mark_processed(self, agent_id: str, filename: str) -> None:
        """Move from inbox/ to processed/"""

    def list_online_agents(self) -> list[dict]:
        """Read all online agents from registry"""

    def get_agent(self, agent_id: str) -> dict | None:
        """Read single agent info from registry"""
```

### MailboxChannel

Follows existing channel pattern (like telegram.py, feishu.py):

```python
class MailboxChannel(BaseChannel):
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = MailboxConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MailboxConfig = config
        self.manager = MailboxManager(Path(self.config.mailboxes_root).expanduser())
        self._running = False

    def _build_card(self) -> dict:
        """Build Agent Card from mailbox config. Identity fields are user-configured."""
        return {
            "agent_id": self.config.agent_id,
            "description": self.config.description or "",
            "capabilities": self.config.capabilities or [],
            "status": "idle",
            "allow_from": self.config.allow_from,
            "max_concurrent_tasks": self.config.max_concurrent_tasks,
            "current_tasks": [],
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }

    async def start(self) -> None:
        """Register agent + start poll loop"""
        self.manager.register(self.config.agent_id, self._build_card())
        self._running = True
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Periodically scan inbox, inject new messages into bus"""
        while self._running:
            messages = self.manager.poll(self.config.agent_id)
            for msg in messages:
                inbound = self._to_inbound(msg)
                await self.bus.publish_inbound(inbound)
                self.manager.mark_processed(self.config.agent_id, msg["filename"])
            self.manager.heartbeat(self.config.agent_id)
            await asyncio.sleep(self.config.poll_interval)

    async def send_message(self, to_id: str, msg: dict) -> None:
        """Send message to another agent's mailbox"""
        # Anti-loop checks
        if to_id in msg.get("trace", []):
            logger.warning(f"Rejecting circular route: {to_id} already in trace")
            return
        if msg.get("ttl", 0) <= 0:
            logger.warning("TTL exhausted, cannot forward")
            return
        msg["ttl"] = msg.get("ttl", 3) - 1
        msg.setdefault("trace", []).append(self.config.agent_id)
        self.manager.send(self.config.agent_id, to_id, msg)

    def _to_inbound(self, msg: dict) -> InboundMessage:
        """Convert mailbox JSON to standard InboundMessage"""
        callback = msg.get("callback", {})
        return InboundMessage(
            channel=callback.get("channel", "mailbox"),
            sender=msg["from"],
            content=self._extract_text(msg),
            session_id=callback.get("session_id") or f"mailbox:{msg['from']}",
            metadata={
                "mailbox_type": msg["type"],
                "mailbox_task": msg.get("task"),
                "mailbox_parts": msg.get("content", {}).get("parts"),
                "mailbox_ttl": msg.get("ttl"),
                "mailbox_trace": msg.get("trace"),
                "reply_to": msg.get("reply_to"),
            },
        )

    async def stop(self) -> None:
        self._running = False
        self.manager.update_status(self.config.agent_id, "offline")

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MailboxConfig().model_dump(by_alias=True)
```

### MailboxConfig

All settings are self-contained within the mailbox channel config.

```python
class MailboxConfig(Base):
    enabled: bool = False
    agent_id: str = ""
    description: str = ""           # optional, for agent discovery
    capabilities: list[str] = []    # optional, for agent discovery
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    max_concurrent_tasks: int = 3
    poll_interval: float = 5.0
    mailboxes_root: str = "~/.nanobot/mailboxes"
```

### Configuration

In `~/.nanobot/config.json`:

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
      "agentId": "coder",
      "description": "负责代码编写和修改的 agent",
      "capabilities": ["code_write", "test_run", "review"],
      "allowFrom": ["researcher"],
      "maxConcurrentTasks": 3,
      "pollInterval": 5,
      "mailboxesRoot": "~/.nanobot/mailboxes"
    }
  }
}
```

Two agents running independently:

```json
// Agent A config — researcher
{
  "channels": {
    "mailbox": {
      "enabled": true,
      "agentId": "researcher",
      "description": "负责信息检索和分析的 agent",
      "capabilities": ["web_search", "code_analysis", "summarization"],
      "allowFrom": ["*"]
    }
  }
}

// Agent B config — coder
{
  "channels": {
    "mailbox": {
      "enabled": true,
      "agentId": "coder",
      "description": "负责代码编写和修改的 agent",
      "capabilities": ["code_write", "test_run", "review"],
      "allowFrom": ["researcher"]
    }
  }
}
```

## Design Principles

- **Zero side effects**: Only new files, no modifications to existing code
- **Channel plugin pattern**: MailboxChannel follows the same interface as all other channels
- **Bus integration**: Mailbox messages become standard `InboundMessage` objects; AgentLoop is unaware of mailbox
- **Callback routing**: Original channel session is preserved through the task lifecycle for seamless user experience
- **Anti-loop by default**: TTL + trace prevents runaway agent conversations without configuration
- **Best-effort deadlines**: Optional `deadline` field for task timeout, not a blocking mechanism
