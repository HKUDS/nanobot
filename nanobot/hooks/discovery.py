"""Discover external hook plugins registered via entry_points."""

from __future__ import annotations

from typing import Any

from loguru import logger


def discover_hook_plugins() -> dict[str, Any]:
    """Scan ``nanobot.hooks`` entry_points group and return {name: loaded_object}.

    Failed loads are logged and skipped so a faulty plugin cannot
    prevent other plugins from loading.
    """
    from importlib.metadata import entry_points

    plugins: dict[str, Any] = {}
    for ep in entry_points(group="nanobot.hooks"):
        try:
            obj = ep.load()
            plugins[ep.name] = obj
        except Exception as e:
            logger.warning("Failed to load hook plugin '{}': {}", ep.name, e)
    return plugins


def register_discovered(center: Any) -> int:
    """Discover external hook plugins and register them with *center*.

    Each loaded object may be:
    - A callable with a ``hook_points`` attribute (list of point names)
    - A mapping ``{point_name: handler}``

    Callables without ``hook_points`` are logged as errors and skipped.

    Returns the number of successfully registered handlers.
    """
    plugins = discover_hook_plugins()
    registered = 0
    for name, obj in plugins.items():
        try:
            if isinstance(obj, dict):
                for point_name, handler in obj.items():
                    center.register_handler(point_name, handler)
                    registered += 1
            elif callable(obj):
                points = getattr(obj, "hook_points", None)
                if points:
                    for point_name in points:
                        center.register_handler(point_name, obj)
                        registered += 1
                elif points is None:
                    raise ValueError(
                        f"Hook plugin '{name}' is callable but has no "
                        f"'hook_points' attribute; cannot determine "
                        f"which points to register for"
                    )
            else:
                logger.warning(
                    "Hook plugin '{}' is not callable and not a dict; skipping",
                    name,
                )
        except Exception as e:
            logger.warning("Error registering hook plugin '{}': {}", name, e)
    return registered
