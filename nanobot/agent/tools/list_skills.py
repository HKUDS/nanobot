"""List skills tool for showing available agent skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import Tool


class ListSkillsTool(Tool):
    """Tool to list all available skills loaded in the workspace."""

    def __init__(self, workspace: str | Path):
        self._workspace = Path(workspace).expanduser()
        self._skills_loader = SkillsLoader(self._workspace)

    @property
    def name(self) -> str:
        return "list_skills"

    @property
    def description(self) -> str:
        return (
            "List all available skills with their names, descriptions, and availability status. "
            "Skills are reusable capabilities loaded from the workspace. "
            "This tool helps answer questions like 'what can you do' or 'what skills do you have'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filter_unavailable": {
                    "type": "boolean",
                    "description": "If true, only show available skills (dependencies installed). "
                                   "If false, show all skills including unavailable ones.",
                },
                "search": {
                    "type": "string",
                    "description": "Optional search term to filter skills by name or description.",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        filter_unavailable: bool = True,
        search: str | None = None,
        **kwargs: Any,
    ) -> str:
        """List all available skills."""
        skills = self._skills_loader.list_skills(filter_unavailable=filter_unavailable)

        # Filter by search term if provided
        if search:
            search_lower = search.lower()
            skills = [
                s
                for s in skills
                if search_lower in s["name"].lower()
                or (s.get("description") and search_lower in s["description"].lower())
            ]

        if not skills:
            if filter_unavailable:
                return "No available skills found. Skills may need dependencies installed."
            return "No skills found in the workspace."

        lines = [f"📚 Available Skills ({len(skills)} total)\n"]

        # Group by source
        builtin = [s for s in skills if s.get("source") == "builtin"]
        workspace_skills = [s for s in skills if s.get("source") == "workspace"]

        if workspace_skills:
            lines.append("## Workspace Skills")
            for skill in workspace_skills:
                status_emoji = "✅" if skill.get("available") else "❌"
                lines.append(f"{status_emoji} **{skill['name']}**")
                if skill.get("description"):
                    lines.append(f"   {skill['description']}")
                if not skill.get("available"):
                    lines.append(f"   ⚠️ Dependencies not installed")
            lines.append("")

        if builtin:
            lines.append("## Built-in Skills")
            for skill in builtin:
                status_emoji = "✅" if skill.get("available") else "❌"
                lines.append(f"{status_emoji} **{skill['name']}**")
                if skill.get("description"):
                    lines.append(f"   {skill['description']}")
            lines.append("")

        return "\n".join(lines)
