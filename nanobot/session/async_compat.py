"""Compatibility bridge for asynchronous SessionManager operations."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from nanobot.utils.cancellation import shield_and_drain

_SessionResult = TypeVar("_SessionResult")


async def call_session_manager(
    manager: object,
    async_method_name: str,
    sync_method: Callable[..., _SessionResult],
    /,
    *args: Any,
    **kwargs: Any,
) -> _SessionResult:
    """Prefer a class-declared coroutine, or offload the established sync contract."""
    class_async_method = inspect.getattr_static(type(manager), async_method_name, None)
    if inspect.iscoroutinefunction(class_async_method):
        async_method = cast(
            Callable[..., Awaitable[_SessionResult]],
            getattr(manager, async_method_name),
        )
        return await async_method(*args, **kwargs)
    return await shield_and_drain(asyncio.to_thread(sync_method, *args, **kwargs))
