"""Outbound helpers for the WebSocket/WebUI wire contract.

AgentLoop uses these without importing a concrete channel plugin; only
``channel == "websocket"`` messages are affected.
"""

from __future__ import annotations

import time
from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

# Wall-clock turn start per ``chat_id`` (websocket only). Survives browser refresh while the
# gateway process stays up; cleared on idle/stop and implicitly dropped on restart.
_WEBSOCKET_TURN_WALL_STARTED_AT: dict[str, float] = {}


def websocket_turn_wall_started_at(chat_id: str) -> float | None:
    """Return ``time.time()`` when the active user turn began, if still running."""
    return _WEBSOCKET_TURN_WALL_STARTED_AT.get(chat_id)


async def publish_turn_run_status(bus: MessageBus, msg: InboundMessage, status: str) -> None:
    """Notify WebSocket clients while a user turn is executing (timing strip)."""
    if msg.channel != "websocket":
        return
    cid = str(msg.chat_id)
    meta: dict[str, Any] = {
        **dict(msg.metadata or {}),
        "_goal_status": True,
        "goal_status": status,
    }
    if status == "running":
        t0 = time.time()
        meta["started_at"] = t0
        _WEBSOCKET_TURN_WALL_STARTED_AT[cid] = t0
    else:
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(cid, None)
    await bus.publish_outbound(
        OutboundMessage(
            channel=msg.channel,
            chat_id=cid,
            content="",
            metadata=meta,
        ),
    )
