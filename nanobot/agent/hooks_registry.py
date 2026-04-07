"""Auto-discovery for AgentHook plugins via entry_points."""

from __future__ import annotations

from importlib.metadata import entry_points
from loguru import logger
from nanobot.agent.hook import AgentHook


def discover_hooks() -> list[AgentHook]:
    """Discover AgentHook plugins registered via nanobot.hooks entry_points."""
    hooks: list[AgentHook] = []
    for ep in entry_points(group="nanobot.hooks"):
        try:
            obj = ep.load()
            # Support both class and factory/instance patterns
            if isinstance(obj, type) and issubclass(obj, AgentHook):
                hooks.append(obj())
                logger.info("Loaded hook plugin: {}", ep.name)
            elif isinstance(obj, AgentHook):
                hooks.append(obj)
                logger.info("Loaded hook plugin (instance): {}", ep.name)
            elif callable(obj):
                instance = obj()
                if isinstance(instance, AgentHook):
                    hooks.append(instance)
                    logger.info("Loaded hook plugin (factory): {}", ep.name)
                else:
                    logger.warning("Hook factory '{}' did not return AgentHook instance", ep.name)
            else:
                logger.warning("Hook entry point '{}' is not an AgentHook", ep.name)
        except Exception:
            logger.exception("Failed to load hook plugin '{}'", ep.name)
    return hooks
