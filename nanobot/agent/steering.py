"""Per-session interruption checking for the steering layer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext

if TYPE_CHECKING:
    from nanobot.bus.events import InboundMessage


class InterruptionChecker:
    """
    Per-session interruption queue.

    Written by ``AgentLoop.run()``; read by ``SteeringHook``.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()

    async def signal(self, msg: InboundMessage) -> None:
        """Push an interrupting message (called from the outer run loop)."""
        await self._queue.put(msg)
        logger.info(
            "Interruption queued for session: {}", msg.content[:60],
        )

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


class SteeringHook(AgentHook):
    """AgentHook that injects pending user interruptions before each LLM call.

    Drop this into the ``hooks`` list of ``AgentLoop`` to enable steering.
    The hook is stateless beyond its reference to the per-session checker.
    """

    def __init__(self, checker: InterruptionChecker) -> None:
        self._checker = checker

    async def before_iteration(self, context: AgentHookContext) -> None:
        pending = self._checker.drain_all()
        if not pending:
            return
        combined = "\n\n---\n\n".join(m.content for m in pending)
        injection = (
            "[The user just sent a new message while you were working. "
            "Read it and decide: continue current work, switch to the "
            "new request, or address both.]\n\n" + combined
        )
        context.messages.append({"role": "user", "content": injection})
        logger.info("Steering: injected {} interruption(s) before LLM call", len(pending))
