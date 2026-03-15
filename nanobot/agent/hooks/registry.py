"""Registry for event-driven hooks."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.agent.hooks.base import Hook, HookEvent, HookResult


class HookRegistry:
    """Registry that dispatches lifecycle events to registered hooks."""

    def __init__(self):
        self._hooks: dict[str, Hook] = {}

    def register(self, hook: Hook) -> None:
        """Register a hook."""
        self._hooks[hook.name] = hook

    def unregister(self, name: str) -> None:
        """Unregister a hook by name."""
        self._hooks.pop(name, None)

    def get_hook(self, name: str) -> Hook | None:
        """Get a hook by name."""
        return self._hooks.get(name)

    # ---- Core event dispatch ----

    def emit(self, event: HookEvent, context: dict | None = None) -> HookResult:
        """Trigger an event, executing all matching hooks by priority.

        For PreToolUse/PostToolUse events, only hooks whose ``matcher``
        regex matches ``context["tool_name"]`` are executed.

        If any hook returns ``proceed=False``, execution short-circuits
        and that result is returned immediately.

        Otherwise the last non-None ``modified_data`` is carried forward.
        """
        ctx = context or {}
        hooks = sorted(self._hooks.values(), key=lambda h: h.priority)
        last_modified: Any = None

        for hook in hooks:
            # Matcher filtering for tool events
            if event in (HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE):
                tool_name = ctx.get("tool_name", "")
                if hook.matcher is not None and not re.search(hook.matcher, tool_name):
                    continue

            try:
                result = hook.on_event(event, ctx)
            except Exception:
                logger.exception("Hook '{}' raised on {}", hook.name, event.value)
                continue

            if not result.proceed:
                logger.info("Hook '{}' blocked event {} : {}", hook.name, event.value, result.reason)
                return result

            if result.modified_data is not None:
                last_modified = result.modified_data
                # Feed modified data forward so next hook sees it
                ctx = {**ctx, "data": last_modified}

        return HookResult(proceed=True, modified_data=last_modified)

    # ---- Convenience methods (delegate to emit) ----

    def apply_skills_filters(self, skills: list[dict]) -> list[dict]:
        """Apply all registered hooks to skills list via PRE_BUILD_CONTEXT."""
        result = self.emit(HookEvent.PRE_BUILD_CONTEXT, {"type": "skills", "data": skills})
        return result.modified_data if result.modified_data is not None else skills
