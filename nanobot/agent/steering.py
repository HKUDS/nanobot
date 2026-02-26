"""Steering layer: per-session interruption checking.

When the outer ``run()`` loop receives a new inbound message for a session
that already has an active task, it pushes the message into the session's
InterruptionChecker.  The inner ``_run_agent_loop`` calls ``drain_all()``
between tool-call batches and injects any pending messages into the
conversation so the LLM can decide how to proceed.

Default behaviour (no checker) is identical to the original single-layer
loop — zero overhead, fully backward-compatible.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.bus.events import InboundMessage


class InterruptionChecker:
    """
    Per-session interruption queue.

    Written by ``AgentLoop.run()``; read by ``_run_agent_loop``.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()

    async def signal(self, msg: InboundMessage) -> None:
        """Push an interrupting message (called from the outer run loop)."""
        await self._queue.put(msg)
        logger.info(
            "Interruption queued for session: {}", msg.content[:60],
        )

    async def check(self) -> InboundMessage | None:
        """Non-blocking peek.  Returns the next pending message or *None*."""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def drain_all(self) -> list[InboundMessage]:
        """Drain all pending messages at once (for batch injection)."""
        msgs: list[InboundMessage] = []
        while True:
            try:
                msgs.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return msgs

    @property
    def has_pending(self) -> bool:
        return not self._queue.empty()
