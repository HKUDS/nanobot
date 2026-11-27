"""Pending input and idle-only turns for one session worker's lifetime."""

from __future__ import annotations

import asyncio
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager

from nanobot.bus.events import InboundMessage
from nanobot.runtime_admission import RuntimeAdmission
from nanobot.utils.cancellation import shield_and_drain


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
    """Serialize input admission and hand each nonempty FIFO to one worker."""

    def __init__(
        self, admission: RuntimeAdmission,
        session_lock: Callable[[str], asyncio.Lock], start_worker: Callable[[str, SessionInbox], None],
        prepare_followup: Callable[[SessionInbox, InboundMessage], Awaitable[InboundMessage | None]],
    ) -> None:
        self._admission = admission
        self._session_lock = session_lock
        self._start_worker = start_worker
        self._prepare_followup = prepare_followup
        self._active: dict[str, SessionInbox] = {}
        self._controls: dict[str, dict[asyncio.Event, tuple[asyncio.Task[object] | None, bool]]] = {}
        self._closed = False
        self._admission_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def _admission_lock(self, key: str) -> asyncio.Lock:
        lock = self._admission_locks.get(key)
        if lock is None:
            lock = self._admission_locks[key] = asyncio.Lock()
        return lock

    def _put(self, message: InboundMessage) -> None:
        key = message.session_key
        if (inbox := self.get(key)) is None:
            inbox = self._active[key] = SessionInbox()
            inbox.put_nowait(message)
            self._start_worker(key, inbox)
        else:
            inbox.put_nowait(message)

    async def enqueue(self, message: InboundMessage) -> None:
        key = message.session_key
        async with self._admission_lock(key):
            self.check_admission()
            with self._admission.activity():
                if (inbox := self.get(key)) is not None:
                    followup = await self._prepare_followup(inbox, message)
                    if followup is None:
                        return
                    message = followup
                self._put(message)

    async def enqueue_if_idle(self, message: InboundMessage, prepare: Callable[[], Awaitable[bool]]) -> bool:
        """Return False if busy; otherwise prepare under exclusion and enqueue on True."""
        key = message.session_key
        async with self._admission_lock(key):
            self.check_admission()
            with self._admission.activity():
                lock = self._session_lock(key)
                if key in self or key in self._controls or lock.locked():
                    return False
                async with lock:
                    await shield_and_drain(self._prepare_and_put(message, prepare))
                    return True

    async def _prepare_and_put(self, message: InboundMessage, prepare: Callable[[], Awaitable[bool]]) -> None:
        if await prepare():
            self._put(message)

    def __getitem__(self, key: str) -> SessionInbox:
        return self._active[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._active)

    def __len__(self) -> int:
        return len(self._active)

    async def close_admission(self) -> None:
        self._closed = True
        # No admitted operation can start a worker after the shutdown snapshot.
        for lock in list(self._admission_locks.values()):
            async with lock:
                pass

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

    @asynccontextmanager
    async def controlling(self, key: str, *, discard: bool = False) -> AsyncGenerator[None]:
        """Accept work into a replacement inbox without starting its worker yet."""
        self.check_admission()
        finished = asyncio.Event()
        controls = self._controls.setdefault(key, {})
        controls[finished] = (asyncio.current_task(), discard)
        try:
            async with self._admission_lock(key):
                pass  # Join any in-flight admission before snapshotting its worker.
            yield
        finally:
            del controls[finished]
            if not controls:
                del self._controls[key]
            finished.set()

    def is_discarding(self, key: str) -> bool:
        return any(discard for _, discard in self._controls.get(key, {}).values())

    async def wait_for_controls(self, key: str | None = None) -> None:
        current = asyncio.current_task()
        while True:
            groups = self._controls.values() if key is None else (self._controls.get(key, {}),)
            pending = next((
                event for group in groups for event, (owner, _) in group.items()
                if owner is not current
            ), None)
            if pending is None:
                return
            await pending.wait()
