"""Plugin registry for memory store backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.memory.base import BaseMemoryStore

_BUILTIN = "normal"


def discover_memory_store(name: str) -> type[BaseMemoryStore]:
    """Return the memory store class for *name*.

    Built-in name: ``"normal"`` → :class:`~nanobot.memory.store.NormalMemoryStore`.
    External plugins are registered via::

        [project.entry-points."nanobot.memory"]
        mybackend = "my_pkg.memory:MyMemoryStore"

    Raises:
        ValueError: if *name* is not found in built-ins or entry_points.
    """
    if name == _BUILTIN:
        from nanobot.memory.store import NormalMemoryStore
        return NormalMemoryStore

    from importlib.metadata import entry_points
    for ep in entry_points(group="nanobot.memory"):
        if ep.name == name:
            try:
                return ep.load()
            except Exception as e:
                logger.error("Failed to load memory plugin '{}': {}", name, e)
                raise

    raise ValueError(
        f"Unknown memory backend: '{name}'. "
        f"Install a plugin that registers nanobot.memory.{name}, "
        f"or use the built-in backend: 'normal'."
    )
