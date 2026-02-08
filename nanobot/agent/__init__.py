"""Agent core module."""

from typing import TYPE_CHECKING, Any

# Keep imports lazy to avoid importing heavy/runtime deps at package import time.
# This allows importing submodules like nanobot.agent.tools.* in lightweight contexts
# (e.g. tests) without requiring the full dependency set.
if TYPE_CHECKING:
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.memory import MemoryStore
    from nanobot.agent.skills import SkillsLoader

__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name == "AgentLoop":
        from nanobot.agent.loop import AgentLoop as v

        return v
    if name == "ContextBuilder":
        from nanobot.agent.context import ContextBuilder as v

        return v
    if name == "MemoryStore":
        from nanobot.agent.memory import MemoryStore as v

        return v
    if name == "SkillsLoader":
        from nanobot.agent.skills import SkillsLoader as v

        return v
    raise AttributeError(name)
