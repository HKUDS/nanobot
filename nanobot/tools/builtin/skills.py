"""Skill loading tool — load skill instructions on demand."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from nanobot.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from nanobot.context.skills import SkillsLoader


class LoadSkillTool(Tool):
    """Load the full instructions for a skill by name.

    The system prompt lists available skills with short descriptions.
    Call this tool to get the complete instructions before using a skill.
    """

    readonly = True
    cacheable = False  # Skill content must be returned in full, never summarized

    def __init__(self, skills_loader: SkillsLoader) -> None:
        self._loader = skills_loader

    name = "load_skill"
    description = (
        "Load the full instructions for a skill by name. "
        "The system prompt lists available skills — call this tool "
        "to get the complete instructions before using a skill."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (e.g., 'obsidian-cli', 'github', 'weather')",
            },
        },
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Load skill content by name."""
        name: str = kwargs["name"]
        content = self._loader.load_skill(name)
        if content is None:
            available = [s["name"] for s in self._loader.list_skills()]
            return ToolResult.fail(
                f"Skill '{name}' not found. Available skills: {', '.join(available)}",
                error_type="not_found",
            )
        stripped = self._loader._strip_frontmatter(content)
        return ToolResult.ok(stripped)


__all__ = ["LoadSkillTool"]
