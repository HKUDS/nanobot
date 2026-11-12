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
    """Finish an accepted operation before propagating caller cancellation.

    Thread workers cannot be stopped by cancelling their awaiting task. Keep
    their result and any subsequent settlement attached until both finish.
    """
    settlement = asyncio.ensure_future(awaitable)
    cancellation: asyncio.CancelledError | None = None

    while not settlement.done():
        try:
            result = await asyncio.shield(settlement)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
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
            # Cancellation wins after the operation's outcome has been observed.
            pass
        raise cancellation
    return settlement.result()
