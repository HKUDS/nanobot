"""Pending input and idle-only turns for one session worker's lifetime."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterator

from nanobot.bus.events import InboundMessage


class SessionInbox(asyncio.Queue[InboundMessage]):
    """Runner injection sees only the input FIFO; the worker also drains idle-only turns."""

    def __init__(self, maxsize: int = 0) -> None:
        super().__init__(maxsize)
        self._deferred: deque[InboundMessage] = deque()

    @property
    def deferred(self) -> tuple[InboundMessage, ...]:
        return tuple(self._deferred)

    def defer(self, msg: InboundMessage) -> None:
        self._deferred.append(msg)

    def next_turn(self) -> InboundMessage | None:
        if not self.empty():
            return self.get_nowait()
        return self._deferred.popleft() if self._deferred else None

    def drain(self) -> Iterator[InboundMessage]:
        """Only for a detached inbox that can no longer accept work."""
        while (msg := self.next_turn()) is not None:
            yield msg
