"""Load skill content by name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        skill_name=StringSchema("Name of the skill to load"),
        required=["skill_name"],
    )
)
class SkillLoadTool(Tool):
    """Load the full content of a skill by name."""

    _scopes = {"core", "subagent"}

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(workspace=Path(ctx.workspace) if ctx.workspace else None)

    @property
    def name(self) -> str:
        return "skill_load"

    @property
    def description(self) -> str:
        return "Load the full content of a skill by name."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, skill_name: str = "", **kwargs: Any) -> str:
        try:
            if not skill_name:
                return "Error: skill_name is required"

            loader = SkillsLoader(self._workspace or Path("."))
            content = loader.load_skills_for_context([skill_name])
            if content is None:
                available = [s["name"] for s in loader.list_skills(filter_unavailable=False)]
                return f"Error: skill '{skill_name}' not found. Available skills: {', '.join(available)}"
            return content
        except Exception as e:
            return f"Error loading skill: {e}"
