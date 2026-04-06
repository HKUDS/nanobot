"""Agent core module."""

from nanobot.agent.context import ContextBuilder
from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.compactor import ContextCompactor, estimate_tokens
from nanobot.agent.delegation import (
    DelegationPlan,
    FileScope,
    MergeReport,
    MergeStrategy,
    ScopedDelegationRunner,
    SubagentOrchestrator,
    SubagentResult,
    SubagentStatus,
    SubagentTask,
)
from nanobot.agent.memory import Consolidator, Dream, MemoryEntry, MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.subagent import SubagentManager

__all__ = [
    "AgentHook",
    "AgentHookContext",
    "AgentLoop",
    "CompositeHook",
    "ContextBuilder",
    "ContextCompactor",
    "DelegationPlan",
    "Dream",
    "estimate_tokens",
    "FileScope",
    "MergeReport",
    "MergeStrategy",
    "ScopedDelegationRunner",
    "SubagentOrchestrator",
    "SubagentResult",
    "SubagentStatus",
    "SubagentTask",
    "MemoryEntry",
    "MemoryStore",
    "SkillsLoader",
    "SubagentManager",
]
