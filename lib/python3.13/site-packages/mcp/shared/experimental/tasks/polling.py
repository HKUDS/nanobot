"""
Shared polling utilities for task operations.

This module provides generic polling logic that works for both client→server
and server→client task polling.

WARNING: These APIs are experimental and may change without notice.
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import anyio

from mcp.shared.experimental.tasks.helpers import is_terminal
from mcp.types import GetTaskResult


async def poll_until_terminal(
    get_task: Callable[[str], Awaitable[GetTaskResult]],
    task_id: str,
    default_interval_ms: int = 500,
) -> AsyncIterator[GetTaskResult]:
    """
    Poll a task until it reaches terminal status.

    This is a generic utility that works for both client→server and server→client
    polling. The caller provides the get_task function appropriate for their direction.

    Args:
        get_task: Async function that takes task_id and returns GetTaskResult
        task_id: The task to poll
        default_interval_ms: Fallback poll interval if server doesn't specify

    Yields:
        GetTaskResult for each poll
    """
    while True:
        status = await get_task(task_id)
        yield status

        if is_terminal(status.status):
            break

        interval_ms = status.pollInterval if status.pollInterval is not None else default_interval_ms
        await anyio.sleep(interval_ms / 1000)
