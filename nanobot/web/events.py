"""Dashboard event bus — broadcasts events to connected WebSocket clients."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

from nanobot.bus.events import DashboardEvent, InboundMessage, OutboundMessage

_MENTION_RE = re.compile(r"^@(\S+)\s+")


class DashboardEventBus:
    """In-memory pub/sub for dashboard WebSocket clients.

    Subscribes to the MessageBus observers and converts messages into
    JSON-serializable dashboard events, then fans them out to all
    connected WebSocket queues.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Create a new subscriber queue. Returns a queue that receives events."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    def broadcast(self, event: dict[str, Any]) -> None:
        """Send an event to all subscribers (non-blocking)."""
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to prevent backpressure
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

    # ------------------------------------------------------------------
    # MessageBus observer callbacks
    # ------------------------------------------------------------------

    async def on_inbound(self, msg: InboundMessage) -> None:
        """Observer callback for inbound messages."""
        # Detect target agent from @mention or metadata
        agent = "main"
        content = msg.content
        target = (msg.metadata or {}).get("_target_agent")
        if target:
            agent = target
            # Strip @mention prefix for display
            m = _MENTION_RE.match(content)
            if m:
                content = content[m.end():]
        elif msg.content.startswith("@"):
            m = _MENTION_RE.match(msg.content)
            if m:
                agent = m.group(1)
                content = msg.content[m.end():]

        self.broadcast({
            "type": "message_in",
            "agent": agent,
            "channel": msg.channel,
            "chat_id": msg.chat_id,
            "sender": msg.sender_id,
            "content": content[:2000],
            "timestamp": msg.timestamp.isoformat(),
            "session_key": msg.session_key,
        })

    async def on_outbound(self, msg: OutboundMessage) -> None:
        """Observer callback for outbound messages."""
        is_progress = msg.metadata.get("_progress", False)
        is_tool_hint = msg.metadata.get("_tool_hint", False)

        # Extract agent name from metadata if available
        agent = msg.metadata.get("_agent", "main")

        self.broadcast({
            "type": "progress" if is_progress else "message_out",
            "agent": agent,
            "channel": msg.channel,
            "chat_id": msg.chat_id,
            "content": msg.content[:2000] if msg.content else "",
            "is_tool_hint": is_tool_hint,
            "session_key": f"{msg.channel}:{msg.chat_id}",
        })

    async def on_dashboard_event(self, event: DashboardEvent) -> None:
        """Observer callback for dashboard-specific events (tool calls, status)."""
        self.broadcast(event.to_dict())
