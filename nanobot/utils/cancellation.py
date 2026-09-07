"""Async cancellation helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_T = TypeVar("_T")


def task_is_cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def shield_and_drain(awaitable: Awaitable[_T]) -> _T:
    """Delay caller cancellation until an accepted operation has fully settled.

    ``asyncio.to_thread`` cannot stop a worker that has already started. Shielding
    keeps cancellation from detaching that worker, and draining also lets any
    post-write in-memory settlement in ``awaitable`` finish. Cancellation is still
    re-raised as soon as the accepted operation is done.
    """
    settlement = asyncio.ensure_future(awaitable)
    cancellation: asyncio.CancelledError | None = None

    while not settlement.done():
        try:
            result = await asyncio.shield(settlement)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except BaseException:
            if cancellation is None:
                raise
            break
        else:
            if cancellation is not None:
                raise cancellation
            return result

    if cancellation is not None:
        try:
            settlement.result()
        except BaseException:
            # The caller's cancellation wins once settlement has been observed.
            pass
        raise cancellation
    return settlement.result()
