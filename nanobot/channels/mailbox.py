"""Mailbox channel for inter-agent communication via filesystem."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


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
        card = {**card}
        card.setdefault("registered_at", datetime.now(timezone.utc).isoformat())
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
        msg = {**msg}
        ts = int(time.time() * 1000)
        unique = uuid.uuid4().hex[:8]
        filename = f"{ts}_{from_id}_{unique}.msg.json"
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
            try:
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
            except Exception:
                logger.exception("Error processing mailbox message {}", filename)
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
        trace: list[str] = list(meta.get("mailbox_trace", []))
        ttl: int = meta.get("mailbox_ttl", 3)

        # Anti-loop: check circular route
        if target in trace:
            logger.warning("Rejecting circular route: {} already in trace", target)
            return
        # Anti-loop: check TTL exhausted
        if ttl <= 0:
            logger.warning("TTL exhausted, cannot forward to {}", target)
            return

        trace.append(self.config.agent_id)
        ttl -= 1

        mailbox_msg: dict[str, Any] = {
            "type": meta.get("mailbox_type", "message"),
            "from": self.config.agent_id,
            "to": target,
            "content": {"parts": [{"type": "text", "text": msg.content}]},
            "ttl": ttl,
            "trace": trace,
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
