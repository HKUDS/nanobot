"""Pending input and idle-only turns for one session worker's lifetime."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager

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


class SessionExecutionClosedError(RuntimeError):
    """Work cannot enter the session dispatcher once it starts shutting down."""


class SessionInboxes(Mapping[str, SessionInbox]):
    """Own inbox admission and the handoff from control cleanup to a new worker."""

    def __init__(self) -> None:
        self._active: dict[str, SessionInbox] = {}
        self._controls: dict[str, dict[asyncio.Event, tuple[asyncio.Task[object] | None, bool]]] = {}
        self._closed = False

    def __getitem__(self, key: str) -> SessionInbox:
        return self._active[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._active)

    def __len__(self) -> int:
        return len(self._active)

    def close_admission(self) -> None:
        self._closed = True

    def check_admission(self) -> None:
        if self._closed:
            raise SessionExecutionClosedError("Session execution is closing")

    def install(self, key: str, inbox: SessionInbox) -> None:
        self.check_admission()
        if key in self:
            raise RuntimeError("Cannot replace a live session inbox")
        self._active[key] = inbox

    def detach(self, key: str, inbox: SessionInbox) -> None:
        if self.get(key) is inbox:
            del self._active[key]

    @contextmanager
    def controlling(self, key: str, *, discard: bool = False) -> Generator[None]:
        """Accept work into a replacement inbox without starting its worker yet."""
        self.check_admission()
        finished = asyncio.Event()
        controls = self._controls.setdefault(key, {})
        controls[finished] = (asyncio.current_task(), discard)
        try:
            yield
        finally:
            del controls[finished]
            if not controls:
                del self._controls[key]
            finished.set()

    def is_discarding(self, key: str) -> bool:
        return any(discard for _, discard in self._controls.get(key, {}).values())

    async def wait_for_controls(self, key: str) -> None:
        while controls := self._controls.get(key):
            await next(iter(controls)).wait()

    async def join_controls(self) -> None:
        """After admission closes, wait for controls still using runtime resources."""
        current = asyncio.current_task()
        pending = [
            finished for controls in self._controls.values()
            for finished, (owner, _) in controls.items() if owner is not current
        ]
        if pending:
            await asyncio.gather(*(finished.wait() for finished in pending))
