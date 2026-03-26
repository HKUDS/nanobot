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
        "IMPORTANT: When the user's request relates to a topic in the Skills section "
        "of your system prompt, call this tool FIRST before taking any other action. "
        "The skill contains specialized instructions for handling the request."
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
        """Load skill content by name.

        Returns a short confirmation as the tool result output (visible to
        the LLM as a tool message) and stores the full skill content in
        ``metadata["skill_content"]``.  The turn loop injects the content
        as a system message so it carries system-level authority.
        """
        name: str = kwargs["name"]
        content = self._loader.load_skill(name)
        if content is None:
            available = [s["name"] for s in self._loader.list_skills()]
            return ToolResult.fail(
                f"Skill '{name}' not found. Available skills: {', '.join(available)}",
                error_type="not_found",
            )
        stripped = self._loader._strip_frontmatter(content)
        transformed = self._loader.transform_for_agent(stripped)
        return ToolResult.ok(
            f"Skill '{name}' loaded. Follow the skill instructions below.",
            skill_content=transformed,
            skill_name=name,
        )


__all__ = ["LoadSkillTool"]
