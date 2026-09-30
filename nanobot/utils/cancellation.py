"""Async cancellation helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

from loguru import logger

_T = TypeVar("_T")
_CURRENT_SCOPE: ContextVar[CancellationScope | None] = ContextVar(
    "nanobot_cancellation_scope", default=None,
)


class CancellationScope:
    """Own runtime stop callbacks; broadcast synchronously, then await cleanup.

    Cancellation is permanent for this scope. Registrations made after the
    broadcast are stopped immediately, including resources admitted across an await.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._callbacks: dict[
            object, tuple[Callable[[], Awaitable[object] | None], bool, Awaitable[object] | None]
        ] = {}
        self._pending: dict[asyncio.Future[object], Awaitable[object] | None] = {}
        self._errors: list[BaseException] = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError

    def register(
        self, stop: Callable[[], Awaitable[object] | None], *, counted: bool = True,
        _owner: Awaitable[object] | None = None,
    ) -> Callable[[], None]:
        """Register a non-blocking stop request and return its release callback."""
        key = object()
        if self.cancelled:
            self._stop(stop, _owner)
        else:
            self._callbacks[key] = (stop, counted, _owner)

        def release() -> None:
            self._callbacks.pop(key, None)

        return release

    def track_task(self, task: asyncio.Task[_T], *, counted: bool = True) -> Callable[[], None]:
        async def join() -> None:
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                # Execution errors belong to the task's caller, not resource cleanup.
                pass

        def stop() -> Awaitable[object]:
            if not task.done() and not task.cancelling():
                task.cancel()
            return join()

        unregister = self.register(stop, counted=counted, _owner=task)

        def done(_: asyncio.Future[_T]) -> None:
            unregister()

        task.add_done_callback(done)

        def release() -> None:
            unregister()
            task.remove_done_callback(done)

        return release

    def _stop(
        self, stop: Callable[[], Awaitable[object] | None], owner: Awaitable[object] | None,
    ) -> None:
        try:
            cleanup = stop()
            if cleanup is not None:
                future = asyncio.ensure_future(cleanup)
                self._pending[future] = owner
                future.add_done_callback(self._cleanup_done)
        except (asyncio.CancelledError, Exception) as exc:
            self._errors.append(exc)

    def _cleanup_done(self, future: asyncio.Future[object]) -> None:
        self._pending.pop(future, None)
        error = asyncio.CancelledError() if future.cancelled() else future.exception()
        if error is not None:
            self._errors.append(error)
            logger.opt(exception=error).error("Cancellation cleanup failed")

    def cancel(self) -> int:
        """Seal admission and notify every resource before yielding to cleanup."""
        if self.cancelled:
            return 0
        self._cancelled = True
        callbacks, self._callbacks = self._callbacks, {}
        for stop, _, owner in callbacks.values():
            self._stop(stop, owner)
        return sum(counted for _, counted, _ in callbacks.values())

    async def wait(self, timeout: float | None = 5.0, *, exclude: Awaitable[object] | None = None) -> None:
        """Wait without interrupting cleanup; exclude an execution waiting on its own cleanup."""
        deadline = asyncio.get_running_loop().time() + timeout if timeout is not None else None
        while pending := tuple(
            future for future, owner in self._pending.items()
            if exclude is None or owner is not exclude
        ):
            remaining = deadline - asyncio.get_running_loop().time() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                logger.warning("Cancellation returned with {} resources still stopping", len(pending))
                break
            await asyncio.wait(pending, timeout=remaining)
        if self._errors:
            errors, self._errors = self._errors, []
            raise BaseExceptionGroup("failed to cancel runtime resources", errors)

    @contextmanager
    def activate(self) -> Generator[None]:
        token = _CURRENT_SCOPE.set(self)
        try:
            yield
        finally:
            _CURRENT_SCOPE.reset(token)

    async def run(self, work: Callable[[], Awaitable[_T]]) -> _T:
        with self.activate():
            self.check()
            return await work()


def current_cancellation_scope() -> CancellationScope | None:
    """Return the owning runtime scope, inherited by spawned asyncio tasks."""
    return _CURRENT_SCOPE.get()


def raise_if_cancelling() -> None:
    """Reject late work even when a dependency consumes the cancellation exception."""
    scope = current_cancellation_scope()
    if scope is not None:
        scope.check()
    if task_is_cancelling():
        raise asyncio.CancelledError


@contextmanager
def cancellation_boundary(*, counted: bool = False) -> Generator[None]:
    """Enroll a tool invocation in its owning scope and reject a late result."""
    raise_if_cancelling()
    scope = current_cancellation_scope()
    task = asyncio.current_task()
    release = scope.track_task(task, counted=counted) if scope is not None and task is not None else None
    try:
        yield
        raise_if_cancelling()
    finally:
        if release is not None:
            release()


def task_is_cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0
