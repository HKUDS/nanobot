"""Cancellation-safe thread dispatch for synchronous session transactions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from nanobot.utils.cancellation import shield_and_drain

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def call(operation: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Run one synchronous session transaction to settlement in a worker."""
    return await shield_and_drain(asyncio.to_thread(operation, *args, **kwargs))
