"""Skill management tool: list, read, create, update, delete workspace skills."""

from __future__ import annotations

from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import BooleanSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        operation=StringSchema(
            "Operation: list (all discoverable skills), get (full SKILL.md), "
            "create / update / delete (workspace skills only; builtin is read-only).",
            enum=["list", "get", "create", "update", "delete"],
        ),
        name=StringSchema("Skill directory name (kebab-case), required for get, create, update, delete"),
        content=StringSchema("Full SKILL.md text for create or update (YAML frontmatter + body)"),
        include_unavailable=BooleanSchema(
            description="For list: if true, include skills whose CLI/env requirements are not met",
            default=False,
        ),
        required=["operation"],
    )
)
class ManageSkillTool(Tool):
    """CRUD for skills under the workspace ``skills/`` directory; read/list includes built-ins."""

    def __init__(self, loader: SkillsLoader):
        self._loader = loader

    @property
    def name(self) -> str:
        return "manage_skill"

    @property
    def description(self) -> str:
        return (
            "Manage agent skills (markdown packages with SKILL.md). "
            "Use operation=list to discover skills; operation=get to load the full SKILL.md "
            "(preferred over read_file for the main skill file). "
            "For scripts/, references/, or assets/ under a skill, use read_file, grep, glob, or exec. "
            "create/update/delete only affect workspace skills (never built-in bundled skills). "
            "delete removes the entire skill directory under workspace/skills/<name>."
        )

    async def execute(
        self,
        operation: str,
        name: str | None = None,
        content: str | None = None,
        include_unavailable: bool = False,
        **kwargs: Any,
    ) -> str:
        op = (operation or "").strip().lower()
        if op == "list":
            return self._op_list(include_unavailable=include_unavailable)
        if op == "get":
            return self._op_get(name)
        if op == "create":
            return self._op_create(name, content)
        if op == "update":
            return self._op_update(name, content)
        if op == "delete":
            return self._op_delete(name)
        return (
            f"Error: unknown operation {operation!r}. "
            "Use list, get, create, update, or delete."
        )

    def _op_list(self, *, include_unavailable: bool) -> str:
        entries = self._loader.list_skills(filter_unavailable=not include_unavailable)
        if not entries:
            return "No skills found."
        lines: list[str] = ["## Skills", ""]
        for e in entries:
            desc = self._loader.describe_skill(e["name"])
            lines.append(f"- **{e['name']}** ({e['source']}): {desc}")
        return "\n".join(lines)

    def _op_get(self, name: str | None) -> str:
        if not name or not str(name).strip():
            return "Error: name is required for get."
        name = str(name).strip()
        loc = self._loader.resolve_skill_location(name)
        if not loc:
            return f"Error: skill {name!r} not found."
        raw = self._loader.load_skill(name)
        if raw is None:
            return f"Error: could not load skill {name!r}."
        available, missing = self._loader.skill_availability(name)
        req_line = f"\n- **requires**: {missing}" if missing else ""
        return (
            f"## Skill: {name}\n"
            f"- **source**: {loc['source']}\n"
            f"- **path**: {loc['path']}\n"
            f"- **skill_dir**: {loc['skill_dir']}\n"
            f"- **available**: {str(available).lower()}"
            f"{req_line}\n\n--- SKILL.md ---\n\n"
            f"{raw}"
        )

    def _op_create(self, name: str | None, content: str | None) -> str:
        if not name or not str(name).strip():
            return "Error: name is required for create."
        if content is None:
            return "Error: content is required for create."
        try:
            self._loader.create_workspace_skill(str(name).strip(), content)
        except ValueError as e:
            return f"Error: {e}"
        return f"Created workspace skill {str(name).strip()!r}."

    def _op_update(self, name: str | None, content: str | None) -> str:
        if not name or not str(name).strip():
            return "Error: name is required for update."
        if content is None:
            return "Error: content is required for update."
        try:
            self._loader.update_workspace_skill(str(name).strip(), content)
        except ValueError as e:
            return f"Error: {e}"
        except PermissionError as e:
            return f"Error: {e}"
        return f"Updated workspace skill {str(name).strip()!r}."

    def _op_delete(self, name: str | None) -> str:
        if not name or not str(name).strip():
            return "Error: name is required for delete."
        try:
            self._loader.delete_workspace_skill(str(name).strip())
        except ValueError as e:
            return f"Error: {e}"
        except PermissionError as e:
            return f"Error: {e}"
        return f"Deleted workspace skill directory {str(name).strip()!r}."
