"""Entry-point plugin discovery for HookCenter.

Plugin contract:
    Plugin objects expose ``hook_events: list[tuple[type, str]]`` —
    list of (event_type, mode) tuples declaring which hook points
    the plugin subscribes to.

    Plugin objects may expose ``hook_streaming: bool`` flag for
    wants_streaming indication.

    Plugin module-level code executes at ``ep.load()`` time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.hooks.center import HookCenter
    from nanobot.hooks.protocols import HookHandler


def discover_hook_plugins(enabled: list[str] | None = None) -> dict[str, "HookHandler"]:
    """Scan ``entry_points(group="nanobot.hooks")`` and return ``{name: handler}``.

    When *enabled* is provided, only plugins in the allowlist are loaded
    (``ep.load()`` is called *after* the allowlist check).  Each entry
    point is loaded independently — a single failed plugin does not
    prevent other plugins from being discovered.
    """
    from importlib.metadata import entry_points

    plugins: dict[str, HookHandler] = {}
    for ep in entry_points(group="nanobot.hooks"):
        if enabled is not None and ep.name not in enabled:
            logger.info("Hook plugin '{}' not in enabled_plugins, skipping", ep.name)
            continue
        try:
            handler = ep.load()
            plugins[ep.name] = handler
        except Exception:
            logger.warning("Failed to load hook plugin '{}'", ep.name)
    return plugins


def register_discovered(center: "HookCenter", config: Any = None) -> None:
    """Discover external hook plugins and register them into *center*.

    Filters by ``config.hooks.enabled_plugins`` allowlist when present.
    The allowlist is enforced *before* ``ep.load()`` so blocked plugins
    never execute their module-level code.  Each plugin must expose
    ``hook_events: list[tuple[type, str]]``.
    """
    enabled = getattr(getattr(config, "hooks", None), "enabled_plugins", None)

    try:
        discovered = discover_hook_plugins(enabled=enabled)
    except Exception:
        logger.warning("entry_points discovery failed, continuing with core hook handlers only")
        return

    for name, handler in discovered.items():
        hook_events = getattr(handler, "hook_events", [])
        if not hook_events:
            logger.warning("Hook plugin '{}' has no hook_events, skipping", name)
            continue

        for event_type, mode in hook_events:
            center.register(event_type, handler, mode)
        logger.debug("Registered hook plugin '{}' with {} events", name, len(hook_events))
