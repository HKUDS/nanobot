"""HookCenter: centralized registry for named hook points."""

from __future__ import annotations

from typing import Callable

from loguru import logger

from nanobot.hooks.context import HookContext, HookResult


class HookCenter:
    """Centralized registry for named hook points.

    Internal developers register hook points and emit them.
    External plugins register handlers via ``register_handler``
    (discovered through entry_points by ``discovery.py``).
    """

    def __init__(self) -> None:
        self._points: dict[str, str] = {}
        self._handlers: dict[str, list[Callable]] = {}

    def register_point(self, name: str, description: str = "") -> None:
        """Declare a named hook point that handlers can attach to."""
        if name not in self._points:
            self._points[name] = description
            self._handlers.setdefault(name, [])
        elif self._points[name] != description and description:
            self._points[name] = description

    def register_handler(
        self,
        point_name: str,
        handler: Callable,
    ) -> None:
        """Register *handler* for the given hook point.

        If the point has not been declared yet it is auto-created
        (useful for external plugins loaded before internal registration).
        Duplicate registrations of the same handler for the same point
        are silently ignored.
        """
        self._handlers.setdefault(point_name, [])
        if handler not in self._handlers[point_name]:
            self._handlers[point_name].append(handler)

    def has_point(self, name: str) -> bool:
        return name in self._points

    def get_point_names(self) -> list[str]:
        return list(self._points.keys())

    def get_handlers(self, name: str) -> list[Callable]:
        return list(self._handlers.get(name, []))

    async def emit(self, name: str, context: HookContext) -> HookResult:
        """Trigger all handlers registered for *name*.

        Returns the final HookResult.  Handlers are called in
        registration order.  Error isolation: a failing handler is
        logged and skipped; it does not prevent other handlers from
        running.
        """
        handlers = self._handlers.get(name, [])
        if not handlers:
            return HookResult(action="continue")

        for handler in handlers:
            try:
                result = await handler(context)
            except Exception:
                logger.exception("HookCenter: handler error for '{}'", name)
                continue

            if result is None:
                continue
            if not isinstance(result, HookResult):
                logger.warning(
                    "HookCenter: handler for '{}' returned {} instead of HookResult or None; ignoring",
                    name,
                    type(result).__name__,
                )
                continue
            if result.action != "continue":
                return result

        return HookResult(action="continue")

    def reset(self) -> None:
        """Clear all registered points and handlers (useful in tests)."""
        self._points.clear()
        self._handlers.clear()


_center: HookCenter | None = None


def get_center() -> HookCenter:
    """Return the global HookCenter singleton."""
    global _center
    if _center is None:
        _center = HookCenter()
    return _center


def reset_center() -> None:
    """Reset the global singleton (for testing only)."""
    global _center
    _center = None
