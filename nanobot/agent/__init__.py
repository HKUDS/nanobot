"""Agent core module.

Keep this package import-light.

Some agent components depend on optional provider backends; importing them
eagerly at package import time makes unrelated modules (e.g. tools) require
those optional dependencies. We therefore expose the public symbols via lazy
imports so that `import nanobot.agent` does not pull provider packages unless
explicitly requested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]

if TYPE_CHECKING:
    from nanobot.agent.context import ContextBuilder as ContextBuilder
    from nanobot.agent.loop import AgentLoop as AgentLoop
    from nanobot.agent.memory import MemoryStore as MemoryStore
    from nanobot.agent.skills import SkillsLoader as SkillsLoader


def __getattr__(name: str) -> Any:
    if name == "AgentLoop":
        from nanobot.agent.loop import AgentLoop

        return AgentLoop
    if name == "ContextBuilder":
        from nanobot.agent.context import ContextBuilder

        return ContextBuilder
    if name == "MemoryStore":
        from nanobot.agent.memory import MemoryStore

        return MemoryStore
    if name == "SkillsLoader":
        from nanobot.agent.skills import SkillsLoader

        return SkillsLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
