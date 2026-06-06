"""Agent core module."""

from blackcat.agent.consolidate import Consolidator
from blackcat.agent.context import ContextBuilder
from blackcat.agent.hook import AgentHook, AgentHookContext, CompositeHook
from blackcat.agent.loop import AgentLoop
from blackcat.agent.memory import MemoryStore
from blackcat.agent.skills import SkillsLoader
from blackcat.agent.subagent import SubagentManager

__all__ = [
    "AgentHook",
    "AgentHookContext",
    "AgentLoop",
    "CompositeHook",
    "Consolidator",
    "ContextBuilder",
    "MemoryStore",
    "SkillsLoader",
    "SubagentManager",
]
