"""Event-loop-local task admission during an explicitly requested maintenance window.

This gate coordinates work in one runtime. It is not an installation/data lock or
proof that another process, a channel, or an external store has stopped writing.
The update owner must still stop and flush those writers before backup/install.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from contextlib import contextmanager


class RuntimeMaintenanceError(RuntimeError):
    """New work cannot enter a runtime held for maintenance."""


class RuntimeBusyError(RuntimeError):
    """Maintenance would interrupt accepted work."""


class RuntimeAdmission:
    """Share between the gateway's bus, agent, cron and local trigger intake.

    All methods run on their owning event-loop thread. Checking, counting work
    and closing admission are synchronous: no task can enter between the idle
    check and the pause. Do not call this object from an installer worker thread.
    """

    def __init__(self) -> None:
        self._paused = False
        self._active = 0
        self._pending_checks: list[Callable[[], bool]] = []
        self._open = asyncio.Event()
        self._open.set()

    @property
    def paused(self) -> bool:
        return self._paused

    def check(self) -> None:
        if self._paused:
            raise RuntimeMaintenanceError(
                "nanobot is preparing an update. Try again after maintenance finishes."
            )

    async def wait_until_open(self) -> None:
        """Pause scheduler intake without consuming or rescheduling pending work."""
        while self._paused:
            await self._open.wait()

    def register_pending_work(self, check: Callable[[], bool]) -> Callable[[], None]:
        """Account for an owner's queued/detached work until it is shut down.

        Like activity(), registration and inspection are event-loop-local. The
        owner removes its check only after closing its writers. Checks must not
        mutate state or yield, so admission can close without an idle-check gap.
        """
        self.check()
        self._pending_checks.append(check)
        registered = True

        def remove() -> None:
            nonlocal registered
            if registered:
                self._pending_checks.remove(check)
                registered = False

        return remove

    @contextmanager
    def activity(self) -> Generator[None, None, None]:
        """Account for accepted work, including its awaited cleanup."""
        self.check()
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1

    @contextmanager
    def pause_if_idle(self, has_pending_work: Callable[[], bool]) -> Generator[None, None, None]:
        """Refuse busy runtimes without cancelling work or leaving intake closed.

        The owner supplies a synchronous view of queued/detached work which
        outlives an ``activity`` call. Hold this context through the handoff;
        releasing it after a refused/aborted update restores prior admission.
        """
        self.check()
        if self._active or has_pending_work() or any(check() for check in self._pending_checks):
            raise RuntimeBusyError(
                "nanobot has pending work. Finish active tasks and retry the update."
            )
        with self.pause_before_start():
            yield

    @contextmanager
    def pause_before_start(self) -> Generator[None, None, None]:
        """Hold a fresh runtime before starting any consumers or external intake.

        Startup may already have reconstructed a durable recovery queue. It must
        not execute that queue until activation. Running gateways must instead
        use pause_if_idle, which also checks their owner's pending-work view.
        """
        self.check()
        if self._active:
            raise RuntimeBusyError("Runtime work has already started")
        self._paused = True
        self._open.clear()
        try:
            yield
        finally:
            self._paused = False
            self._open.set()
