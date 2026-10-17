"""Agent core module."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.hook import (
        AgentHook,
        AgentHookContext,
        AgentRunHookContext,
        AgentTurnHookContext,
        AgentTurnHookFactory,
        CompositeHook,
    )
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.memory import MemoryStore
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.subagent import SubagentManager


_EXPORTS = {
    "AgentHook": "nanobot.agent.hook",
    "AgentHookContext": "nanobot.agent.hook",
    "AgentRunHookContext": "nanobot.agent.hook",
    "AgentTurnHookContext": "nanobot.agent.hook",
    "AgentTurnHookFactory": "nanobot.agent.hook",
    "AgentLoop": "nanobot.agent.loop",
    "CompositeHook": "nanobot.agent.hook",
    "ContextBuilder": "nanobot.agent.context",
    "MemoryStore": "nanobot.agent.memory",
    "SkillsLoader": "nanobot.agent.skills",
    "SubagentManager": "nanobot.agent.subagent",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "AgentHook",
    "AgentHookContext",
    "AgentRunHookContext",
    "AgentTurnHookContext",
    "AgentTurnHookFactory",
    "AgentLoop",
    "CompositeHook",
    "ContextBuilder",
    "MemoryStore",
    "SkillsLoader",
    "SubagentManager",
]
