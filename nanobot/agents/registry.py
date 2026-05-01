"""Agent discovery via entry_points for external agent plugins."""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agents import BaseAgent

_INTERNAL_AGENTS = frozenset({"__init__"})


def discover_agents() -> dict[str, type["BaseAgent"]]:
    """Discover all agents: built-in (pkgutil) merged with external (entry_points).

    Built-in agents take priority — an external plugin cannot shadow a built-in name.
    """
    import nanobot.agents as agents_pkg

    from nanobot.agents import BaseAgent

    builtin: dict[str, type[BaseAgent]] = {}

    for _, name, ispkg in pkgutil.iter_modules(agents_pkg.__path__):
        if ispkg or name in _INTERNAL_AGENTS:
            continue
        try:
            mod = __import__(f"nanobot.agents.{name}", fromlist=[name])
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr is not BaseAgent:
                    builtin[attr.name] = attr
                    logger.debug("Discovered built-in agent: {}", attr.name)
        except Exception as e:
            logger.debug("Skipping agent '{}': {}", name, e)

    return builtin


def discover_plugins() -> dict[str, type["BaseAgent"]]:
    """Discover external agent plugins registered via entry_points."""
    from importlib.metadata import entry_points

    from nanobot.agents import BaseAgent

    plugins: dict[str, type[BaseAgent]] = {}

    for ep in entry_points(group="nanobot.agents"):
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, BaseAgent):
                plugins[ep.name] = cls
                logger.info("Loaded agent plugin: {}", ep.name)
            else:
                logger.warning("Entry '{}' is not a BaseAgent subclass", ep.name)
        except Exception as e:
            logger.warning("Failed to load agent plugin '{}': {}", ep.name, e)

    return plugins


def discover_all() -> dict[str, type["BaseAgent"]]:
    """Return all agents: built-in (pkgutil) merged with external (entry_points).

    Built-in agents take priority — an external plugin cannot shadow a built-in name.
    """
    from nanobot.agents import BaseAgent

    builtin = discover_agents()
    external = discover_plugins()

    builtin_names = set(builtin)
    shadowed = set(external) & builtin_names
    if shadowed:
        logger.warning("Agent plugin(s) shadowed by built-in (ignored): {}", shadowed)

    return {**external, **builtin}
