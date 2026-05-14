"""Outbound helpers for the WebSocket/WebUI wire contract.

AgentLoop uses these without importing a concrete channel plugin; only
``channel == "websocket"`` messages are affected.
"""

from __future__ import annotations

import time
from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


async def publish_turn_run_status(bus: MessageBus, msg: InboundMessage, status: str) -> None:
    """Notify WebSocket clients while a user turn is executing (timing strip)."""
    if msg.channel != "websocket":
        return
    meta: dict[str, Any] = {
        **dict(msg.metadata or {}),
        "_goal_status": True,
        "goal_status": status,
    }
    if status == "running":
        meta["started_at"] = time.time()
    await bus.publish_outbound(
        OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="",
            metadata=meta,
        ),
    )
