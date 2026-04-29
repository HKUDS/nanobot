"""Hook handler protocol for the HookCenter."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nanobot.hooks.context import HookContext, HookResult


@runtime_checkable
class HookHandler(Protocol):
    """Protocol for hook handlers registered with HookCenter."""

    async def __call__(self, context: HookContext) -> HookResult | None:
        ...


__all__ = [
    "HookHandler",
]
