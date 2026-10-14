"""Restricted Dream tool for recording a reusable workflow."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from typing import TYPE_CHECKING

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.memory import MemoryStore


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("Generalized task, without names or private paths.", max_length=200),
        steps=ArraySchema(
            StringSchema("Reusable action in order.", max_length=400),
            min_items=2,
            max_items=12,
        ),
        tools=ArraySchema(
            StringSchema("Tool used in the workflow.", max_length=80),
            max_items=12,
        ),
        tags=ArraySchema(
            StringSchema("Short retrieval keyword.", max_length=80),
            min_items=1,
            max_items=12,
        ),
        required=["task", "steps", "tools", "tags"],
    )
)
class SaveLearnedSkillTool(Tool):
    """Validate and deduplicate skill-memory records produced by Dream."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "save_learned_skill"

    @property
    def description(self) -> str:
        return "Save a reusable workflow from a completed multi-step task to learned memory."

    async def execute(
        self, task: str, steps: list[str], tools: list[str], tags: list[str]
    ) -> str | ToolResult:
        try:
            saved = self._store.save_skill({
                "task": task, "steps": steps, "tools": tools, "tags": tags,
            })
        except ValueError as exc:
            return ToolResult.error(str(exc))
        return "Saved learned skill." if saved else "Skipped similar learned skill."
