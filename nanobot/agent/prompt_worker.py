"""Bounded background work and detached snapshots for prompt preparation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import copy_context
from copy import deepcopy
from typing import Any, ParamSpec, TypeVar

_Args = ParamSpec("_Args")
_Result = TypeVar("_Result")


class PromptWorker:
    """Serialize preparation jobs without making callers wait after cancellation."""

    def __init__(self) -> None:
        self._slot = asyncio.Semaphore(1)
        self._jobs: set[Awaitable[object]] = set()

    async def run(
        self, operation: Callable[_Args, _Result],
        *args: _Args.args, **kwargs: _Args.kwargs,
    ) -> _Result:
        await self._slot.acquire()
        context = copy_context()

        def prepare() -> _Result:
            return context.run(operation, *args, **kwargs)

        try:
            future = asyncio.get_running_loop().run_in_executor(None, prepare)
        except BaseException:
            self._slot.release()
            raise
        self._jobs.add(future)

        def finished(done: asyncio.Future[_Result]) -> None:
            self._jobs.discard(done)
            self._slot.release()
            if not done.cancelled():
                done.exception()

        future.add_done_callback(finished)
        # Cancelling the caller cannot stop its thread; release the slot on completion.
        return await asyncio.shield(future)


async def copy_messages_on_loop(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detach loop-owned records while yielding between bounded batches."""
    copied: list[dict[str, Any]] = []
    memo: dict[int, Any] = {id(messages): copied}
    for start in range(0, len(messages), 64):
        copied.extend(deepcopy(message, memo) for message in messages[start:start + 64])
        await asyncio.sleep(0)
    return copied
