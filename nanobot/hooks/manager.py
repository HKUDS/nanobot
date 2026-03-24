"""Hook manager — register and fire hooks by event type."""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.hooks.base import Hook, HookContext


class HookManager:
    """Registry for hooks, keyed by event type."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Hook]] = {}

    def register(self, event_type: str, hook: Hook) -> None:
        self._hooks.setdefault(event_type, []).append(hook)
        logger.debug("Registered hook {} for event {}", hook.name, event_type)

    async def fire(self, event_type: str, context: HookContext, **kwargs: Any) -> list[Any]:
        """Fire all hooks for *event_type*. Returns list of results."""
        hooks = self._hooks.get(event_type, [])
        if not hooks:
            return []

        results: list[Any] = []
        for hook in hooks:
            try:
                result = await hook.execute(context, **kwargs)
                results.append(result)
            except Exception:
                logger.exception("Hook {} failed for event {}", hook.name, event_type)
                results.append(None)
        return results

    def has_hooks(self, event_type: str) -> bool:
        return bool(self._hooks.get(event_type))
