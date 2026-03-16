"""Memory tools: update bot identity, user profile, and save general memories.

These tools execute silently (no user confirmation) and persist information
to the workspace markdown files that form the bot's long-term context.
"""

import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class UpdateBotIdentityTool(Tool):
    """Update the bot's identity stored in SOUL.md."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "update_bot_identity"

    @property
    def description(self) -> str:
        return (
            "Update the bot's identity (name, personality, values, communication style). "
            "This executes immediately without user confirmation. "
            "A visual indicator is automatically shown to the user — do not mention "
            "file names, tools, or internal details in your response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The bot's new name",
                },
                "personality_traits": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of personality traits (e.g. ['Warm and empathetic', 'Playfully witty'])",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of values (e.g. ['Honesty', 'User privacy'])",
                },
                "communication_style": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of communication style notes (e.g. ['Casual and friendly', 'Use analogies'])",
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> str:
        bot_name = kwargs.get("name")
        personality_traits = kwargs.get("personality_traits")
        values = kwargs.get("values")
        communication_style = kwargs.get("communication_style")

        if not bot_name:
            return "Error: 'name' is required"

        try:
            soul_path = self._resolve_soul_path()
            content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

            content = self._update_name(content, bot_name)
            if personality_traits:
                content = self._update_list_section(content, "Personality", personality_traits)
            if values:
                content = self._update_list_section(content, "Values", values)
            if communication_style:
                content = self._update_list_section(content, "Communication Style", communication_style)

            soul_path.parent.mkdir(parents=True, exist_ok=True)
            soul_path.write_text(content, encoding="utf-8")

            changes = [f"name → {bot_name}"]
            if personality_traits:
                changes.append("personality")
            if values:
                changes.append("values")
            if communication_style:
                changes.append("communication style")

            return f"[memory_saved] Updated bot identity: {', '.join(changes)}"
        except Exception as e:
            return f"Error updating bot identity: {e}"

    def _resolve_soul_path(self) -> Path:
        if self._workspace:
            return self._workspace / "SOUL.md"
        return Path("SOUL.md")

    @staticmethod
    def _update_name(content: str, new_name: str) -> str:
        pattern = r"^(# Soul\s*\n\s*I am )\S+(\s.*|$)"
        if re.search(pattern, content, re.MULTILINE):
            return re.sub(
                r"(# Soul\s*\n\s*I am )\S+",
                rf"\g<1>{new_name}",
                content,
                count=1,
            )
        if content.strip():
            return re.sub(
                r"^# Soul\s*$",
                f"# Soul\n\nI am {new_name}, a personal AI assistant.",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        return f"# Soul\n\nI am {new_name}, a personal AI assistant.\n\n## Personality\n\n- Helpful and friendly\n\n## Values\n\n- User privacy and safety\n\n## Communication Style\n\n- Be clear and direct\n"

    @staticmethod
    def _update_list_section(content: str, heading: str, items: list[str]) -> str:
        new_list = "\n".join(f"- {item}" for item in items)
        pattern = rf"(## {re.escape(heading)}\s*\n)(?:- .+\n?)+"
        if re.search(pattern, content):
            return re.sub(pattern, rf"\g<1>{new_list}\n", content)
        content = content.rstrip() + f"\n\n## {heading}\n\n{new_list}\n"
        return content


class UpdateUserProfileTool(Tool):
    """Update the user's profile stored in USER.md."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "update_user_profile"

    @property
    def description(self) -> str:
        return (
            "Update the user's profile (name, timezone, language, preferences, work context). "
            "This executes immediately without user confirmation. "
            "A visual indicator is automatically shown to the user — do not mention "
            "file names, tools, or internal details in your response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The user's name",
                },
                "timezone": {
                    "type": "string",
                    "description": "The user's timezone (e.g. 'America/New_York', 'UTC+8')",
                },
                "language": {
                    "type": "string",
                    "description": "The user's preferred language (e.g. 'English')",
                },
                "communication_style": {
                    "type": "string",
                    "enum": ["Casual", "Professional", "Technical"],
                    "description": "Preferred communication style",
                },
                "technical_level": {
                    "type": "string",
                    "enum": ["Beginner", "Intermediate", "Expert"],
                    "description": "User's technical comfort level",
                },
                "role": {
                    "type": "string",
                    "description": "User's primary role (e.g. 'developer', 'designer')",
                },
                "projects": {
                    "type": "string",
                    "description": "What the user is working on",
                },
                "tools": {
                    "type": "string",
                    "description": "Tools/languages/frameworks the user uses",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        if not any(kwargs.get(k) for k in (
            "name", "timezone", "language", "communication_style",
            "technical_level", "role", "projects", "tools",
        )):
            return "Error: at least one field must be provided"

        try:
            user_path = self._resolve_user_path()
            content = user_path.read_text(encoding="utf-8") if user_path.exists() else ""

            changes: list[str] = []

            field_map = {
                "name": ("Name", kwargs.get("name")),
                "timezone": ("Timezone", kwargs.get("timezone")),
                "language": ("Language", kwargs.get("language")),
                "role": ("Primary Role", kwargs.get("role")),
                "projects": ("Main Projects", kwargs.get("projects")),
                "tools": ("Tools You Use", kwargs.get("tools")),
            }

            for key, (label, value) in field_map.items():
                if value:
                    content = self._update_field(content, label, value)
                    changes.append(key)

            if comm_style := kwargs.get("communication_style"):
                content = self._update_checkbox(content, "Communication Style", comm_style)
                changes.append("communication style")

            if tech_level := kwargs.get("technical_level"):
                content = self._update_checkbox(content, "Technical Level", tech_level)
                changes.append("technical level")

            user_path.parent.mkdir(parents=True, exist_ok=True)
            user_path.write_text(content, encoding="utf-8")

            return f"[memory_saved] Updated user profile: {', '.join(changes)}"
        except Exception as e:
            return f"Error updating user profile: {e}"

    def _resolve_user_path(self) -> Path:
        if self._workspace:
            return self._workspace / "USER.md"
        return Path("USER.md")

    @staticmethod
    def _update_field(content: str, label: str, value: str) -> str:
        pattern = rf"(\*\*{re.escape(label)}\*\*:\s*).*"
        if re.search(pattern, content):
            return re.sub(pattern, rf"\g<1>{value}", content, count=1)
        return content

    @staticmethod
    def _update_checkbox(content: str, section_heading: str, selected: str) -> str:
        in_section = False
        lines = content.split("\n")
        result = []
        for line in lines:
            if line.strip().startswith("###") and section_heading in line:
                in_section = True
                result.append(line)
                continue
            if in_section and line.strip().startswith("###"):
                in_section = False
            if in_section and re.match(r"^- \[[ x]\] ", line):
                option_text = re.sub(r"^- \[[ x]\] ", "", line).strip()
                if option_text.lower() == selected.lower():
                    result.append(f"- [x] {option_text}")
                else:
                    result.append(f"- [ ] {option_text}")
                continue
            result.append(line)
        return "\n".join(result)


class SaveMemoryTool(Tool):
    """Save a fact or note to MEMORY.md for long-term persistence."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return (
            "Save an important fact, preference, or note to long-term memory. "
            "Use this for any information worth remembering across sessions that doesn't "
            "fit into bot identity or user profile updates. "
            "This executes immediately without user confirmation. "
            "A visual indicator is automatically shown to the user — do not mention "
            "file names, tools, or internal details in your response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact, preference, or note to remember",
                },
                "section": {
                    "type": "string",
                    "enum": ["User Information", "Preferences", "Project Context", "Important Notes"],
                    "description": "Which section to add the memory under (defaults to 'Important Notes')",
                },
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs: Any) -> str:
        memory_content = kwargs.get("content")
        section = kwargs.get("section", "Important Notes")

        if not memory_content:
            return "Error: 'content' is required"

        try:
            memory_path = self._resolve_memory_path()
            existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""

            if not existing.strip():
                existing = (
                    "# Long-term Memory\n\n"
                    "## User Information\n\n"
                    "## Preferences\n\n"
                    "## Project Context\n\n"
                    "## Important Notes\n"
                )

            section_pattern = rf"(## {re.escape(section)}\s*\n)"
            if re.search(section_pattern, existing):
                existing = re.sub(
                    section_pattern,
                    rf"\g<1>\n- {memory_content}\n",
                    existing,
                    count=1,
                )
            else:
                existing = existing.rstrip() + f"\n\n## {section}\n\n- {memory_content}\n"

            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(existing, encoding="utf-8")

            preview = memory_content[:60] + "..." if len(memory_content) > 60 else memory_content
            return f"[memory_saved] Saved to memory: {preview}"
        except Exception as e:
            return f"Error saving memory: {e}"

    def _resolve_memory_path(self) -> Path:
        if self._workspace:
            return self._workspace / "memory" / "MEMORY.md"
        return Path("memory") / "MEMORY.md"
