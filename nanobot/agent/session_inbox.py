"""Pending input and idle-only turns for one session worker's lifetime."""

from __future__ import annotations

import asyncio
import weakref
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
        self._admission_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._edits: dict[str, asyncio.Event] = {}

    def admission_lock(self, key: str) -> asyncio.Lock:
        lock = self._admission_locks.get(key)
        if lock is None:
            lock = self._admission_locks[key] = asyncio.Lock()
        return lock

    def idle(self, key: str) -> bool:
        return key not in self and key not in self._controls

    @contextmanager
    def reserving_edit(self, key: str) -> Generator[SessionInbox]:
        """Under admission_lock, install before yielding; hand off only a committed input."""
        inbox = SessionInbox()
        self.install(key, inbox)
        finished = self._edits[key] = asyncio.Event()
        try:
            yield inbox
        finally:
            if inbox.empty():
                self.detach(key, inbox)
            del self._edits[key]
            finished.set()

    async def wait_for_edit(self, key: str) -> None:
        if finished := self._edits.get(key):
            await finished.wait()

    async def join_edits(self) -> None:
        if self._edits:
            await asyncio.gather(*(finished.wait() for finished in self._edits.values()))

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
