"""Run-local FIFO input batches and bounded terminal waits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.agent.execution_policy import ExecutionControlError
from nanobot.bus.events import InboundMessage


@dataclass
class PendingInputs:
    """Consume only a prepared prefix; leave independent turns to the session worker."""

    queue: asyncio.Queue[InboundMessage]
    prepare: Callable[[InboundMessage], Awaitable[dict[str, Any] | None]]
    consume: Callable[[Iterable[InboundMessage]], None] | None = None
    session_key: str | None = None
    running_subagents: Callable[[], int] | None = None
    terminal_wait_seconds: float = 300.0
    _terminal_wait_deadline: float | None = field(default=None, init=False, repr=False)

    async def drain(
        self, *, first_msg: InboundMessage | None = None,
    ) -> list[dict[str, Any]]:
        # Fix the boundary before preparation can await; later arrivals belong
        # to the next model step even if they arrive during context resolution.
        pending = [first_msg] if first_msg is not None else []
        for _ in range(self.queue.qsize()):
            pending.append(self.queue.get_nowait())

        consumed = 0
        try:
            converted: list[dict[str, Any]] = []
            for message in pending:
                row = await self.prepare(message)
                if row is None:
                    break
                converted.append(row)
            if self.consume is not None:
                try:
                    self.consume(pending[:len(converted)])
                except Exception as exc:
                    raise ExecutionControlError("could not accept consumed inputs") from exc
            consumed = len(converted)
            return converted
        finally:
            # Conversion or authorization failure returns the entire snapshot.
            # A FIFO barrier returns the unconsumed suffix ahead of later inputs.
            unconsumed = pending[consumed:]
            if unconsumed:
                later = [self.queue.get_nowait() for _ in range(self.queue.qsize())]
                for message in [*unconsumed, *later]:
                    self.queue.put_nowait(message)

    async def wait_at_terminal(self) -> list[dict[str, Any]]:
        items = await self.drain()
        if items or self.running_subagents is None or self.running_subagents() == 0:
            return items

        now = asyncio.get_running_loop().time()
        if self._terminal_wait_deadline is None:
            self._terminal_wait_deadline = now + self.terminal_wait_seconds
        remaining = self._terminal_wait_deadline - now
        if remaining <= 0:
            return []

        try:
            message = await asyncio.wait_for(self.queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.warning(
                "Timeout waiting for sub-agent completion before session {} exits",
                self.session_key,
            )
            return []
        return await self.drain(first_msg=message)
