"""Hook auto-discovery: built-in modules + external plugins.

Mirrors the pattern used by ``nanobot/channels/registry.py`` and
``nanobot/agent/tools/loader.py``.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.hook import AgentHook, AgentTurnHookFactory

_INTERNAL_SKIP = frozenset({"__init__", "discovery"})


def discover_builtin() -> tuple[list[AgentTurnHookFactory], list[AgentHook]]:
    """Scan ``nanobot/agent/hooks/`` and collect factories and instances."""
    import nanobot.agent.hooks as pkg

    factories: list[AgentTurnHookFactory] = []
    instances: list[AgentHook] = []
    for _importer, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if name in _INTERNAL_SKIP or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f".{name}", pkg.__name__)
        except Exception:
            logger.exception("Failed to import hook module: {}", name)
            continue
        try:
            f = getattr(mod, "hook_factories", [])
            factories.extend(f)
        except Exception:
            pass
        try:
            h = getattr(mod, "hooks", [])
            instances.extend(h)
        except Exception:
            pass
    return factories, instances


def discover_plugins() -> tuple[list[AgentTurnHookFactory], list[AgentHook]]:
    """Load external hooks registered via ``entry_points(group='nanobot.hooks')``."""
    from importlib.metadata import entry_points

    factories: list[AgentTurnHookFactory] = []
    instances: list[AgentHook] = []
    try:
        eps = entry_points(group="nanobot.hooks")
    except Exception:
        return factories, instances
    for ep in eps:
        try:
            mod = ep.load()
            f = getattr(mod, "hook_factories", [])
            factories.extend(f)
            h = getattr(mod, "hooks", [])
            instances.extend(h)
        except Exception:
            logger.warning("Failed to load hook plugin '{}'", ep.name)
    return factories, instances


def discover_all() -> tuple[list[AgentTurnHookFactory], list[AgentHook]]:
    """Return all hooks: built-in + plugins."""
    bf, bi = discover_builtin()
    pf, pi = discover_plugins()
    return bf + pf, bi + pi