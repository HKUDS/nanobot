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

    def __init__(
        self, workspace: Path | None = None, skills_loader: SkillsLoader | None = None
    ) -> None:
        self._workspace = workspace
        self._skills_loader = skills_loader
        if self._skills_loader is None:
            self._skills_loader = SkillsLoader(workspace or Path("."))

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        workspace = Path(ctx.workspace) if ctx.workspace else None
        loader = ctx.skills_loader if ctx.skills_loader else SkillsLoader(workspace or Path("."))
        return cls(workspace=workspace, skills_loader=loader)

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

            if self._skills_loader is None:
                return "Error: skills_loader is not initialized"

            all_skills = self._skills_loader.list_skills(filter_unavailable=False)
            all_names = {skill["name"] for skill in all_skills}
            if skill_name not in all_names:
                available = ", ".join(sorted(all_names)) or "(none)"
                return f"Error: skill '{skill_name}' not found. Available skills: {available}"

            available_names = {
                skill["name"] for skill in self._skills_loader.list_skills(filter_unavailable=True)
            }
            if skill_name not in available_names:
                meta = self._skills_loader._get_skill_meta(skill_name)
                missing = self._skills_loader._get_missing_requirements(meta)
                detail = f": {missing}" if missing else ""
                return f"Error: skill '{skill_name}' is unavailable{detail}"

            content = self._skills_loader.load_skills_for_context([skill_name])
            if not content:
                return f"Error: skill '{skill_name}' has no loadable content"
            return content
        except Exception as e:
            return f"Error loading skill: {e}"
