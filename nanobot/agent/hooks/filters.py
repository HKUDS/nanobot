"""Built-in hook implementations."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.hooks.base import Hook, HookEvent, HookResult
from nanobot.agent.hooks.storage import HookStorage


class SkillsEnabledFilter(Hook):
    """Filter disabled skills from context (prompt)."""

    def __init__(self, workspace: Path):
        self._storage = HookStorage(workspace)

    @property
    def name(self) -> str:
        return "skills_enabled_filter"

    @property
    def priority(self) -> int:
        return 100

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        """Handle PRE_BUILD_CONTEXT to filter disabled skills."""
        if event != HookEvent.PRE_BUILD_CONTEXT:
            return HookResult()
        if context.get("type") != "skills":
            return HookResult()

        skills = context.get("data", [])
        disabled = self._storage.get_disabled_skills()
        filtered = [s for s in skills if s["name"] not in disabled]
        return HookResult(modified_data=filtered)
