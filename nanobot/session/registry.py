"""Plugin registry for session manager backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.session.base import BaseSessionManager

_BUILTIN = "normal"


def discover_session_manager(name: str) -> type[BaseSessionManager]:
    """Return the session manager class for *name*.

    Built-in name: ``"normal"`` → :class:`~nanobot.session.manager.NormalSessionManager`.
    External plugins are registered via::

        [project.entry-points."nanobot.sessions"]
        mybackend = "my_pkg.session:MySessionManager"

    Raises:
        ValueError: if *name* is not found in built-ins or entry_points.
    """
    if name == _BUILTIN:
        from nanobot.session.manager import NormalSessionManager
        return NormalSessionManager

    from importlib.metadata import entry_points
    for ep in entry_points(group="nanobot.sessions"):
        if ep.name == name:
            try:
                return ep.load()
            except Exception as e:
                logger.error("Failed to load session plugin '{}': {}", name, e)
                raise

    raise ValueError(
        f"Unknown session backend: '{name}'. "
        f"Install a plugin that registers nanobot.sessions.{name}, "
        f"or use the built-in backend: 'normal'."
    )
