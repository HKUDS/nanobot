# Multi-Agent Mailbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a file-system-based mailbox channel plugin for inter-agent communication. Zero modifications to existing code.

**Architecture:** MailboxManager handles low-level file I/O (atomic writes, polling, registry). MailboxChannel is a standard nanobot channel plugin that polls inbox and injects messages into the bus. The LLM uses the existing `MessageTool` with `channel="mailbox"` and `chat_id="<target_agent_id>"` to send messages to other agents — MailboxChannel.send() handles the rest.

**Tech Stack:** Python 3.12+, asyncio, pydantic, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `nanobot/channels/mailbox.py` | MailboxManager + MailboxConfig + MailboxChannel — single file, same as all other channels |
| `tests/channels/test_mailbox.py` | All tests: MailboxManager, MailboxChannel, integration |

**Existing files modified: None**

---

### Task 1: MailboxManager — File Operations (inside mailbox.py)

**Files:**
- Create: `nanobot/channels/mailbox.py`
- Create: `tests/channels/test_mailbox.py`

- [ ] **Step 1: Write failing tests for MailboxManager**

Create `tests/channels/test_mailbox.py`:

```python
"""Tests for MailboxManager (file operations) and MailboxChannel."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.mailbox import MailboxManager, MailboxChannel, MailboxConfig


# --- MailboxManager Tests ---

@pytest.fixture
def root(tmp_path: Path) -> Path:
    mailboxes = tmp_path / "mailboxes"
    mailboxes.mkdir()
    return mailboxes


@pytest.fixture
def mgr(root: Path) -> MailboxManager:
    return MailboxManager(root)


class TestRegister:
    def test_register_creates_agent_entry(self, mgr: MailboxManager, root: Path):
        card = {"agent_id": "researcher", "description": "test agent"}
        mgr.register("researcher", card)
        registry = json.loads((root / "_registry.json").read_text())
        assert "researcher" in registry
        assert registry["researcher"]["agent_id"] == "researcher"

    def test_register_creates_directories(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder"})
        assert (root / "coder" / "inbox").is_dir()
        assert (root / "coder" / "processed").is_dir()

    def test_register_overwrite(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder", "status": "idle"})
        mgr.register("coder", {"agent_id": "coder", "status": "busy"})
        registry = json.loads((root / "_registry.json").read_text())
        assert registry["coder"]["status"] == "busy"


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder"})
        before = json.loads((root / "_registry.json").read_text())["coder"]["last_heartbeat"]
        time.sleep(0.01)
        mgr.heartbeat("coder")
        after = json.loads((root / "_registry.json").read_text())["coder"]["last_heartbeat"]
        assert after >= before


class TestUpdateStatus:
    def test_update_status(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder", "status": "idle"})
        mgr.update_status("coder", "busy", current_tasks=["task_1"])
        registry = json.loads((root / "_registry.json").read_text())
        assert registry["coder"]["status"] == "busy"
        assert registry["coder"]["current_tasks"] == ["task_1"]


class TestSendAndPoll:
    def test_send_creates_message_file(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder"})
        mgr.register("researcher", {"agent_id": "researcher"})
        msg = {"type": "message", "content": {"parts": [{"type": "text", "text": "hello"}]}}
        mgr.send("researcher", "coder", msg)
        files = list((root / "coder" / "inbox").glob("*.msg.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["from"] == "researcher"
        assert data["to"] == "coder"

    def test_poll_returns_new_messages_sorted(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder"})
        mgr.register("a1", {"agent_id": "a1"})
        mgr.register("a2", {"agent_id": "a2"})
        mgr.send("a1", "coder", {"type": "message", "content": {"parts": []}})
        time.sleep(0.01)
        mgr.send("a2", "coder", {"type": "task", "content": {"parts": []}})
        messages = mgr.poll("coder")
        assert len(messages) == 2
        assert messages[0]["from"] == "a1"
        assert messages[1]["from"] == "a2"

    def test_mark_processed_moves_file(self, mgr: MailboxManager, root: Path):
        mgr.register("coder", {"agent_id": "coder"})
        mgr.register("researcher", {"agent_id": "researcher"})
        mgr.send("researcher", "coder", {"type": "message", "content": {"parts": []}})
        messages = mgr.poll("coder")
        mgr.mark_processed("coder", messages[0]["_filename"])
        assert len(list((root / "coder" / "inbox").glob("*.msg.json"))) == 0
        assert len(list((root / "coder" / "processed").glob("*.msg.json"))) == 1


class TestListAndGetAgents:
    def test_list_online_agents(self, mgr: MailboxManager, root: Path):
        mgr.register("researcher", {"agent_id": "researcher", "status": "idle"})
        mgr.register("coder", {"agent_id": "coder", "status": "busy"})
        agents = mgr.list_online_agents()
        ids = {a["agent_id"] for a in agents}
        assert ids == {"researcher", "coder"}

    def test_get_agent_not_found(self, mgr: MailboxManager):
        assert mgr.get_agent("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Documents\GitHub\nanobot\.worktrees\n2n && uv run pytest tests/channels/test_mailbox.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement MailboxManager (first part of mailbox.py)**

Create `nanobot/channels/mailbox.py` with just the MailboxManager class:

```python
"""Mailbox channel for inter-agent communication via filesystem."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MailboxManager — low-level file operations
# ---------------------------------------------------------------------------


class MailboxManager:
    """File-system operations for agent mailboxes."""

    def __init__(self, mailboxes_root: Path) -> None:
        self.root = Path(mailboxes_root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- registry --

    def _registry_path(self) -> Path:
        return self.root / "_registry.json"

    def _read_registry(self) -> dict:
        path = self._registry_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_registry(self, data: dict) -> None:
        path = self._registry_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _ensure_dirs(self, agent_id: str) -> None:
        agent_dir = self.root / agent_id
        (agent_dir / "inbox").mkdir(parents=True, exist_ok=True)
        (agent_dir / "processed").mkdir(parents=True, exist_ok=True)

    def register(self, agent_id: str, card: dict) -> None:
        self._ensure_dirs(agent_id)
        registry = self._read_registry()
        card["registered_at"] = card.get(
            "registered_at", datetime.now(timezone.utc).isoformat()
        )
        card["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        registry[agent_id] = card
        self._write_registry(registry)

    def heartbeat(self, agent_id: str) -> None:
        registry = self._read_registry()
        if agent_id in registry:
            registry[agent_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            self._write_registry(registry)

    def update_status(
        self, agent_id: str, status: str, current_tasks: list[str] | None = None
    ) -> None:
        registry = self._read_registry()
        if agent_id in registry:
            registry[agent_id]["status"] = status
            if current_tasks is not None:
                registry[agent_id]["current_tasks"] = current_tasks
            self._write_registry(registry)

    # -- message I/O --

    def send(self, from_id: str, to_id: str, msg: dict) -> None:
        self._ensure_dirs(to_id)
        ts = int(time.time() * 1000)
        filename = f"{ts}_{from_id}.msg.json"
        msg.setdefault("id", f"msg_{ts}_{from_id}")
        msg.setdefault("from", from_id)
        msg.setdefault("to", to_id)
        msg.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        filepath = self.root / to_id / "inbox" / filename
        tmp = filepath.with_suffix(".tmp")
        tmp.write_text(json.dumps(msg, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, filepath)

    def poll(self, agent_id: str) -> list[dict]:
        inbox = self.root / agent_id / "inbox"
        if not inbox.is_dir():
            return []
        messages = []
        for f in sorted(inbox.glob("*.msg.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filename"] = f.name
            messages.append(data)
        return messages

    def mark_processed(self, agent_id: str, filename: str) -> None:
        src = self.root / agent_id / "inbox" / filename
        dst = self.root / agent_id / "processed" / filename
        if src.exists():
            os.replace(src, dst)

    # -- discovery --

    def list_online_agents(self) -> list[dict]:
        registry = self._read_registry()
        return [card for card in registry.values() if card.get("status") != "offline"]

    def get_agent(self, agent_id: str) -> dict | None:
        return self._read_registry().get(agent_id)


# ---------------------------------------------------------------------------
# MailboxConfig — channel configuration
# ---------------------------------------------------------------------------


class MailboxConfig(Base):
    """Mailbox channel configuration."""

    enabled: bool = False
    agent_id: str = ""
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    max_concurrent_tasks: int = 3
    poll_interval: float = 5.0
    mailboxes_root: str = "~/.nanobot/mailboxes"


# ---------------------------------------------------------------------------
# MailboxChannel — channel plugin
# ---------------------------------------------------------------------------


class MailboxChannel(BaseChannel):
    """Channel plugin for inter-agent communication via filesystem mailboxes.

    The LLM sends messages to other agents using the existing MessageTool:
        MessageTool(channel='mailbox', chat_id='<target_agent_id>', content='...')

    This produces an OutboundMessage routed to MailboxChannel.send(),
    which writes to the target agent's mailbox.
    """

    name = "mailbox"
    display_name = "Mailbox"

    def __init__(self, config: Any, bus: Any) -> None:
        if isinstance(config, dict):
            config = MailboxConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MailboxConfig = config
        root = Path(self.config.mailboxes_root).expanduser()
        self.manager = MailboxManager(root)
        self._running = False
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.manager.register(self.config.agent_id, self._build_card())
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while self._running:
            await self._poll_once()
            self.manager.heartbeat(self.config.agent_id)
            await asyncio.sleep(self.config.poll_interval)

    async def _poll_once(self) -> None:
        messages = self.manager.poll(self.config.agent_id)
        for msg in messages:
            filename = msg.pop("_filename", "")
            callback = msg.get("callback")
            if callback and callback.get("channel") and callback.get("chat_id"):
                await self._handle_callback_message(msg, callback)
            else:
                await self._handle_message(
                    sender_id=msg["from"],
                    chat_id=msg["from"],
                    content=self._extract_text(msg),
                    metadata=self._build_metadata(msg),
                )
            if filename:
                self.manager.mark_processed(self.config.agent_id, filename)

    async def _handle_callback_message(self, msg: dict, callback: dict) -> None:
        if not self.is_allowed(msg["from"]):
            logger.warning("Mailbox: access denied from {}", msg["from"])
            return
        inbound = InboundMessage(
            channel=callback["channel"],
            sender_id=msg["from"],
            chat_id=callback["chat_id"],
            content=self._extract_text(msg),
            metadata=self._build_metadata(msg),
            session_key_override=callback.get("session_id"),
        )
        await self.bus.publish_inbound(inbound)

    def _extract_text(self, msg: dict) -> str:
        parts = msg.get("content", {}).get("parts", [])
        texts = [p["text"] for p in parts if p.get("type") == "text" and "text" in p]
        return "\n".join(texts) if texts else ""

    def _build_metadata(self, msg: dict) -> dict[str, Any]:
        return {
            "mailbox_type": msg.get("type", "message"),
            "mailbox_task": msg.get("task"),
            "mailbox_parts": msg.get("content", {}).get("parts"),
            "mailbox_ttl": msg.get("ttl"),
            "mailbox_trace": msg.get("trace"),
            "reply_to": msg.get("reply_to"),
        }

    async def send(self, msg: OutboundMessage) -> None:
        target = msg.chat_id
        meta = msg.metadata or {}
        mailbox_msg: dict[str, Any] = {
            "type": meta.get("mailbox_type", "message"),
            "from": self.config.agent_id,
            "to": target,
            "content": {"parts": [{"type": "text", "text": msg.content}]},
            "ttl": meta.get("mailbox_ttl", 3),
            "trace": [self.config.agent_id],
        }
        if meta.get("mailbox_task"):
            mailbox_msg["task"] = meta["mailbox_task"]
        if meta.get("mailbox_callback"):
            mailbox_msg["callback"] = meta["mailbox_callback"]
        self.manager.send(self.config.agent_id, target, mailbox_msg)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        self.manager.update_status(self.config.agent_id, "offline")

    def _build_card(self) -> dict:
        return {
            "agent_id": self.config.agent_id,
            "description": self.config.description,
            "capabilities": self.config.capabilities,
            "status": "idle",
            "allow_from": self.config.allow_from,
            "max_concurrent_tasks": self.config.max_concurrent_tasks,
            "current_tasks": [],
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MailboxConfig().model_dump(by_alias=True)
```

- [ ] **Step 4: Run MailboxManager tests**

Run: `cd D:\Documents\GitHub\nanobot\.worktrees\n2n && uv run pytest tests/channels/test_mailbox.py::TestRegister tests/channels/test_mailbox.py::TestHeartbeat tests/channels/test_mailbox.py::TestUpdateStatus tests/channels/test_mailbox.py::TestSendAndPoll tests/channels/test_mailbox.py::TestListAndGetAgents -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/channels/mailbox.py tests/channels/test_mailbox.py
git commit -m "feat: add MailboxManager and MailboxChannel for inter-agent communication"
```

---

### Task 2: MailboxChannel — Channel Plugin Tests

**Files:**
- Create: `nanobot/channels/mailbox.py`
- Create: `tests/channels/test_mailbox_channel.py`

- [ ] **Step 1: Write failing tests for MailboxChannel**

Create `tests/channels/test_mailbox_channel.py`:

```python
"""Tests for MailboxChannel."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.mailbox import MailboxChannel, MailboxConfig


@pytest.fixture
def bus():
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    root = tmp_path / "mailboxes"
    root.mkdir()
    return root


def _make_channel(bus, tmp_root: Path, **overrides) -> MailboxChannel:
    cfg = {
        "enabled": True,
        "agentId": "coder",
        "description": "test coder agent",
        "capabilities": ["code_write"],
        "allowFrom": ["*"],
        "maxConcurrentTasks": 3,
        "pollInterval": 0.1,
        "mailboxesRoot": str(tmp_root),
    }
    cfg.update(overrides)
    return MailboxChannel(cfg, bus)


class TestConfig:
    def test_default_config(self):
        config = MailboxConfig()
        data = config.model_dump(by_alias=True)
        assert data["enabled"] is False
        assert data["agentId"] == ""
        assert data["allowFrom"] == ["*"]

    def test_config_from_dict(self):
        cfg = MailboxConfig.model_validate({
            "enabled": True,
            "agentId": "researcher",
            "allowFrom": ["coder"],
            "pollInterval": 10,
        })
        assert cfg.agent_id == "researcher"
        assert cfg.allow_from == ["coder"]
        assert cfg.poll_interval == 10


class TestChannelAttributes:
    def test_name(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        assert ch.name == "mailbox"

    def test_display_name(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        assert ch.display_name == "Mailbox"


class TestStartAndStop:
    def test_start_registers_agent(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())
        registry = json.loads((tmp_root / "_registry.json").read_text())
        assert "coder" in registry
        assert registry["coder"]["description"] == "test coder agent"
        asyncio.get_event_loop().run_until_complete(ch.stop())

    def test_stop_marks_offline(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())
        asyncio.get_event_loop().run_until_complete(ch.stop())
        registry = json.loads((tmp_root / "_registry.json").read_text())
        assert registry["coder"]["status"] == "offline"

    def test_stop_idempotent(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.stop())
        asyncio.get_event_loop().run_until_complete(ch.stop())


class TestPollAndInbound:
    def test_poll_delivers_inbound_message(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("researcher", {"agent_id": "researcher"})
        mgr.send("researcher", "coder", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "hello from researcher"}]},
        })

        asyncio.get_event_loop().run_until_complete(ch._poll_once())

        bus.publish_inbound.assert_called_once()
        call_args = bus.publish_inbound.call_args[0][0]
        assert call_args.channel == "mailbox"
        assert call_args.sender_id == "researcher"
        assert "hello from researcher" in call_args.content

        asyncio.get_event_loop().run_until_complete(ch.stop())

    def test_poll_with_callback_routes_to_original_session(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("researcher", {"agent_id": "researcher"})
        mgr.send("researcher", "coder", {
            "type": "task_update",
            "content": {"parts": [{"type": "text", "text": "task done"}]},
            "callback": {
                "session_id": "feishu:user_123",
                "channel": "feishu",
                "chat_id": "user_123",
            },
        })

        asyncio.get_event_loop().run_until_complete(ch._poll_once())

        bus.publish_inbound.assert_called_once()
        call_args = bus.publish_inbound.call_args[0][0]
        assert call_args.channel == "feishu"
        assert call_args.session_key_override == "feishu:user_123"
        assert call_args.chat_id == "user_123"

        asyncio.get_event_loop().run_until_complete(ch.stop())

    def test_poll_respects_allow_from(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root, allowFrom=["researcher"])
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("stranger", {"agent_id": "stranger"})
        mgr.send("stranger", "coder", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "unauthorized"}]},
        })

        asyncio.get_event_loop().run_until_complete(ch._poll_once())

        bus.publish_inbound.assert_not_called()

        asyncio.get_event_loop().run_until_complete(ch.stop())

    def test_poll_marks_processed(self, bus, tmp_root):
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("researcher", {"agent_id": "researcher"})
        mgr.send("researcher", "coder", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "hello"}]},
        })

        asyncio.get_event_loop().run_until_complete(ch._poll_once())

        inbox_files = list((tmp_root / "coder" / "inbox").glob("*.msg.json"))
        processed_files = list((tmp_root / "coder" / "processed").glob("*.msg.json"))
        assert len(inbox_files) == 0
        assert len(processed_files) == 1

        asyncio.get_event_loop().run_until_complete(ch.stop())


class TestSend:
    def test_send_writes_to_target_mailbox(self, bus, tmp_root):
        """MailboxChannel.send() is called by ChannelManager when OutboundMessage
        has channel='mailbox'. It writes to the target agent's inbox."""
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("researcher", {"agent_id": "researcher"})

        from nanobot.bus.events import OutboundMessage
        msg = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="task completed",
            metadata={},
        )
        asyncio.get_event_loop().run_until_complete(ch.send(msg))

        files = list((tmp_root / "researcher" / "inbox").glob("*.msg.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["from"] == "coder"
        assert data["to"] == "researcher"
        assert data["ttl"] == 3
        assert "coder" in data["trace"]

        asyncio.get_event_loop().run_until_complete(ch.stop())

    def test_send_uses_existing_message_tool(self, bus, tmp_root):
        """Verify the flow: LLM calls MessageTool(channel='mailbox', chat_id='researcher')
        → OutboundMessage → ChannelManager → MailboxChannel.send()"""
        ch = _make_channel(bus, tmp_root)
        asyncio.get_event_loop().run_until_complete(ch.start())

        from nanobot.channels.mailbox import MailboxManager
        mgr = MailboxManager(tmp_root)
        mgr.register("researcher", {"agent_id": "researcher"})

        # Simulate what MessageTool produces
        from nanobot.bus.events import OutboundMessage
        outbound = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="please write a sort function",
        )
        asyncio.get_event_loop().run_until_complete(ch.send(outbound))

        files = list((tmp_root / "researcher" / "inbox").glob("*.msg.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert "sort function" in data["content"]["parts"][0]["text"]

        asyncio.get_event_loop().run_until_complete(ch.stop())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Documents\GitHub\nanobot\.worktrees\n2n && uv run pytest tests/channels/test_mailbox_channel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nanobot.channels.mailbox'`

- [ ] **Step 3: Implement MailboxConfig and MailboxChannel**

Create `nanobot/channels/mailbox.py`:

```python
"""Mailbox channel for inter-agent communication via filesystem."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.channels.mailbox import MailboxManager
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.config.schema import Base

logger = logging.getLogger(__name__)


class MailboxConfig(Base):
    """Mailbox channel configuration."""

    enabled: bool = False
    agent_id: str = ""
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    max_concurrent_tasks: int = 3
    poll_interval: float = 5.0
    mailboxes_root: str = "~/.nanobot/mailboxes"


class MailboxChannel(BaseChannel):
    """Channel plugin for inter-agent communication via filesystem mailboxes.

    The LLM sends messages to other agents using the existing MessageTool:
        MessageTool(channel='mailbox', chat_id='<target_agent_id>', content='...')

    This produces an OutboundMessage routed to MailboxChannel.send(),
    which writes to the target agent's mailbox.
    """

    name = "mailbox"
    display_name = "Mailbox"

    def __init__(self, config: Any, bus: Any) -> None:
        if isinstance(config, dict):
            config = MailboxConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MailboxConfig = config
        root = Path(self.config.mailboxes_root).expanduser()
        self.manager = MailboxManager(root)
        self._running = False
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Register agent and start poll loop."""
        self.manager.register(self.config.agent_id, self._build_card())
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Periodically scan inbox and inject messages into bus."""
        while self._running:
            await self._poll_once()
            self.manager.heartbeat(self.config.agent_id)
            await asyncio.sleep(self.config.poll_interval)

    async def _poll_once(self) -> None:
        """Single poll cycle: read inbox, inject to bus, mark processed."""
        messages = self.manager.poll(self.config.agent_id)
        for msg in messages:
            filename = msg.pop("_filename", "")
            callback = msg.get("callback")
            if callback and callback.get("channel") and callback.get("chat_id"):
                await self._handle_callback_message(msg, callback)
            else:
                await self._handle_message(
                    sender_id=msg["from"],
                    chat_id=msg["from"],
                    content=self._extract_text(msg),
                    metadata=self._build_metadata(msg),
                )
            if filename:
                self.manager.mark_processed(self.config.agent_id, filename)

    async def _handle_callback_message(self, msg: dict, callback: dict) -> None:
        """Route message to original session (e.g., Feishu) via callback info."""
        if not self.is_allowed(msg["from"]):
            logger.warning("Mailbox: access denied from {}", msg["from"])
            return
        inbound = InboundMessage(
            channel=callback["channel"],
            sender_id=msg["from"],
            chat_id=callback["chat_id"],
            content=self._extract_text(msg),
            metadata=self._build_metadata(msg),
            session_key_override=callback.get("session_id"),
        )
        await self.bus.publish_inbound(inbound)

    def _extract_text(self, msg: dict) -> str:
        """Extract plain text from message content parts."""
        parts = msg.get("content", {}).get("parts", [])
        texts = [p["text"] for p in parts if p.get("type") == "text" and "text" in p]
        return "\n".join(texts) if texts else ""

    def _build_metadata(self, msg: dict) -> dict[str, Any]:
        """Build metadata dict from mailbox message."""
        return {
            "mailbox_type": msg.get("type", "message"),
            "mailbox_task": msg.get("task"),
            "mailbox_parts": msg.get("content", {}).get("parts"),
            "mailbox_ttl": msg.get("ttl"),
            "mailbox_trace": msg.get("trace"),
            "reply_to": msg.get("reply_to"),
        }

    async def send(self, msg: OutboundMessage) -> None:
        """Handle outbound message routed from ChannelManager.

        Called when LLM uses MessageTool with channel='mailbox'.
        Writes message to the target agent's mailbox file.
        Auto-adds TTL, trace, and callback info.
        """
        target = msg.chat_id
        meta = msg.metadata or {}
        mailbox_msg: dict[str, Any] = {
            "type": meta.get("mailbox_type", "message"),
            "from": self.config.agent_id,
            "to": target,
            "content": {"parts": [{"type": "text", "text": msg.content}]},
            "ttl": meta.get("mailbox_ttl", 3),
            "trace": [self.config.agent_id],
        }
        if meta.get("mailbox_task"):
            mailbox_msg["task"] = meta["mailbox_task"]
        if meta.get("mailbox_callback"):
            mailbox_msg["callback"] = meta["mailbox_callback"]
        self.manager.send(self.config.agent_id, target, mailbox_msg)

    async def stop(self) -> None:
        """Stop polling and mark offline."""
        if not self._running:
            return
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        self.manager.update_status(self.config.agent_id, "offline")

    def _build_card(self) -> dict:
        """Build Agent Card for registry from mailbox config."""
        return {
            "agent_id": self.config.agent_id,
            "description": self.config.description,
            "capabilities": self.config.capabilities,
            "status": "idle",
            "allow_from": self.config.allow_from,
            "max_concurrent_tasks": self.config.max_concurrent_tasks,
            "current_tasks": [],
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MailboxConfig().model_dump(by_alias=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Documents\GitHub\nanobot\.worktrees\n2n && uv run pytest tests/channels/test_mailbox_channel.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/channels/mailbox.py tests/channels/test_mailbox.py
git commit -m "feat: add MailboxChannel plugin for inter-agent communication"
```

---

### Task 3: Integration Tests

**Files:**
- Modify: `tests/channels/test_mailbox.py` — append integration tests

- [ ] **Step 1: Append integration tests to test_mailbox.py**

```python
"""Integration test: two agents communicating via mailbox."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.channels.mailbox import MailboxChannel
from nanobot.channels.mailbox import MailboxManager
from nanobot.bus.events import OutboundMessage


@pytest.fixture
def root(tmp_path: Path) -> Path:
    mailboxes = tmp_path / "mailboxes"
    mailboxes.mkdir()
    return mailboxes


@pytest.fixture
def bus_a():
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


@pytest.fixture
def bus_b():
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


def _make_channel(bus, root: Path, agent_id: str) -> MailboxChannel:
    return MailboxChannel({
        "enabled": True,
        "agentId": agent_id,
        "description": f"{agent_id} agent",
        "allowFrom": ["*"],
        "maxConcurrentTasks": 3,
        "pollInterval": 0.05,
        "mailboxesRoot": str(root),
    }, bus)


class TestTwoAgentCommunication:
    @pytest.mark.asyncio
    async def test_agent_a_sends_agent_b_receives(self, root: Path, bus_a, bus_b):
        """Agent A uses MessageTool(channel='mailbox', chat_id='coder') →
        MailboxChannel.send() writes to coder's inbox →
        Agent B polls and receives the message."""
        ch_a = _make_channel(bus_a, root, "researcher")
        ch_b = _make_channel(bus_b, root, "coder")
        await ch_a.start()
        await ch_b.start()

        # Simulate what MessageTool produces: OutboundMessage(channel='mailbox', chat_id='coder')
        outbound = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="please write a sort function",
        )
        await ch_a.send(outbound)

        # Agent B polls inbox
        await ch_b._poll_once()
        bus_b.publish_inbound.assert_called_once()
        msg = bus_b.publish_inbound.call_args[0][0]
        assert msg.channel == "mailbox"
        assert msg.sender_id == "researcher"
        assert "sort function" in msg.content
        # Verify TTL and trace are auto-added
        assert msg.metadata["mailbox_ttl"] == 3
        assert "researcher" in msg.metadata["mailbox_trace"]

        await ch_a.stop()
        await ch_b.stop()

    @pytest.mark.asyncio
    async def test_agent_b_sends_response_back(self, root: Path, bus_a, bus_b):
        """Agent B responds via MessageTool(channel='mailbox', chat_id='researcher') →
        Agent A receives the response."""
        ch_a = _make_channel(bus_a, root, "researcher")
        ch_b = _make_channel(bus_b, root, "coder")
        await ch_a.start()
        await ch_b.start()

        # Agent B responds
        response = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="sort function completed: sort_by_mtime()",
        )
        await ch_b.send(response)

        # Agent A polls inbox
        await ch_a._poll_once()
        bus_a.publish_inbound.assert_called_once()
        msg = bus_a.publish_inbound.call_args[0][0]
        assert "sort function completed" in msg.content
        assert msg.sender_id == "coder"

        await ch_a.stop()
        await ch_b.stop()

    @pytest.mark.asyncio
    async def test_callback_routes_to_original_feishu_session(self, root: Path, bus_a, bus_b):
        """Agent A sends task with callback. Agent B responds with callback.
        Agent A's MailboxChannel routes the response to the original Feishu session."""
        ch_a = _make_channel(bus_a, root, "researcher")
        ch_b = _make_channel(bus_b, root, "coder")
        await ch_a.start()
        await ch_b.start()

        # Agent A sends task with callback metadata (simulating LLM adding callback info)
        task_outbound = OutboundMessage(
            channel="mailbox",
            chat_id="coder",
            content="do work",
            metadata={
                "mailbox_callback": {
                    "channel": "feishu",
                    "chat_id": "user_123",
                    "session_id": "feishu:user_123",
                },
            },
        )
        await ch_a.send(task_outbound)

        # Agent B receives task
        await ch_b._poll_once()
        task_msg = bus_b.publish_inbound.call_args[0][0]

        # Agent B responds with the callback carried forward
        response_outbound = OutboundMessage(
            channel="mailbox",
            chat_id="researcher",
            content="work done",
            metadata={
                "mailbox_callback": {
                    "channel": "feishu",
                    "chat_id": "user_123",
                    "session_id": "feishu:user_123",
                },
            },
        )
        await ch_b.send(response_outbound)

        # Agent A receives response — should route to feishu session
        await ch_a._poll_once()
        bus_a.publish_inbound.assert_called_once()
        update = bus_a.publish_inbound.call_args[0][0]
        assert update.channel == "feishu"
        assert update.session_key_override == "feishu:user_123"
        assert update.chat_id == "user_123"

        await ch_a.stop()
        await ch_b.stop()

    @pytest.mark.asyncio
    async def test_anti_loop_trace(self, root: Path, bus_a):
        """Messages with trace info are preserved in metadata for LLM awareness."""
        ch_a = _make_channel(bus_a, root, "researcher")
        await ch_a.start()

        mgr = MailboxManager(root)
        mgr.register("coder", {"agent_id": "coder"})
        mgr.send("coder", "researcher", {
            "type": "task",
            "ttl": 1,
            "trace": ["researcher", "coder"],
            "content": {"parts": [{"type": "text", "text": "bounced message"}]},
        })

        await ch_a._poll_once()
        bus_a.publish_inbound.assert_called_once()
        msg = bus_a.publish_inbound.call_args[0][0]
        assert msg.metadata["mailbox_ttl"] == 1
        assert "researcher" in msg.metadata["mailbox_trace"]
        assert "coder" in msg.metadata["mailbox_trace"]

        await ch_a.stop()

    @pytest.mark.asyncio
    async def test_allow_from_blocks_unauthorized(self, root: Path, bus_a):
        """Agent with allowFrom=['coder'] rejects messages from 'stranger'."""
        ch_a = MailboxChannel({
            "enabled": True,
            "agentId": "researcher",
            "allowFrom": ["coder"],
            "pollInterval": 0.05,
            "mailboxesRoot": str(root),
        }, bus_a)
        await ch_a.start()

        mgr = MailboxManager(root)
        mgr.register("stranger", {"agent_id": "stranger"})
        mgr.send("stranger", "researcher", {
            "type": "message",
            "content": {"parts": [{"type": "text", "text": "should be blocked"}]},
        })

        await ch_a._poll_once()
        bus_a.publish_inbound.assert_not_called()

        await ch_a.stop()

    @pytest.mark.asyncio
    async def test_registry_discovery(self, root: Path, bus_a, bus_b):
        """Both agents register and can discover each other via registry."""
        ch_a = _make_channel(bus_a, root, "researcher")
        ch_b = _make_channel(bus_b, root, "coder")
        await ch_a.start()
        await ch_b.start()

        mgr = MailboxManager(root)
        agents = mgr.list_online_agents()
        ids = {a["agent_id"] for a in agents}
        assert "researcher" in ids
        assert "coder" in ids

        # Verify descriptions are registered
        researcher = mgr.get_agent("researcher")
        assert researcher["description"] == "researcher agent"

        await ch_a.stop()
        await ch_b.stop()
```

- [ ] **Step 2: Run integration tests**

Run: `cd D:\Documents\GitHub\nanobot\.worktrees\n2n && uv run pytest tests/channels/test_mailbox.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/channels/test_mailbox.py
git commit -m "test: add mailbox integration tests"
```

---

## How It Works End-to-End

```
LLM calls: MessageTool(channel="mailbox", chat_id="coder", content="write sort")
    ↓
OutboundMessage(channel="mailbox", chat_id="coder")
    ↓
ChannelManager._dispatch_outbound() routes to MailboxChannel.send()
    ↓
MailboxChannel.send() writes to ~/.nanobot/mailboxes/coder/inbox/
    ↓
Agent B's MailboxChannel._poll_once() reads inbox
    ↓
Converts to InboundMessage → bus.publish_inbound()
    ↓
AgentLoop processes as normal message
```

No new tools. No code modifications. Pure channel plugin.

---

## Self-Review

### Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| File-system mailbox storage | Task 1 (MailboxManager) |
| Atomic writes (.tmp → rename) | Task 1 (MailboxManager.send) |
| Agent discovery / Agent Card | Task 2 (MailboxChannel._build_card) |
| Agent states (idle/busy/offline) | Task 2 (start/stop + update_status) |
| Message types (message/task) | Task 2 (MailboxChannel.send), Task 3 (integration) |
| TTL + trace anti-loop | Task 2 (send auto-adds), Task 3 (integration) |
| Callback routing to original session | Task 2 (_handle_callback_message), Task 3 (integration) |
| allowFrom access control | Task 2 (uses BaseChannel.is_allowed), Task 3 (integration) |
| MailboxConfig (all fields) | Task 2 (MailboxConfig) |
| Zero modifications to existing code | Confirmed: 1 new file (mailbox.py) + 1 test file |

### Placeholder Scan

No TBD/TODO/placeholder patterns. All steps contain complete code.

### Type Consistency

- `MailboxManager(root: Path)` — consistent across all tasks
- `MailboxConfig.model_validate(config)` in `__init__`
- `InboundMessage(channel, sender_id, chat_id, content, metadata, session_key_override)` — matches dataclass
- `OutboundMessage(channel, chat_id, content, metadata)` — matches dataclass
- `MailboxChannel.name = "mailbox"` — matches config key and registry discovery
