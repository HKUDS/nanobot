"""Skill management tools: list, view, and manage agent skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters

if TYPE_CHECKING:
    from nanobot.agent.skill_evo.skill_store import SkillStore
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config.schema import SkillsConfig


# ---------------------------------------------------------------------------
# SkillsListTool
# ---------------------------------------------------------------------------


@tool_parameters({
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "Optional filter to only show skills whose name starts with this prefix.",
        },
    },
    "required": [],
})
class SkillsListTool(Tool):
    """List all available skills with metadata."""

    def __init__(self, catalog: SkillsLoader) -> None:
        self._catalog = catalog

    @property
    def name(self) -> str:
        return "skills_list"

    @property
    def description(self) -> str:
        return (
            "List available skills (name, description, source, mutable). "
            "Use skill_view(name) to load full content."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        prefix = kwargs.get("category") or None
        entries = self._catalog.list_skills(filter_unavailable=False)
        results: list[dict[str, Any]] = []
        for entry in entries:
            skill_name = entry["name"]
            if prefix and not skill_name.startswith(prefix):
                continue
            description = self._catalog._get_skill_description(skill_name)
            source = entry.get("source", "unknown")
            mutable = source == "workspace"
            supporting = self._catalog.list_supporting_files(skill_name)
            results.append({
                "name": skill_name,
                "description": description,
                "source": source,
                "mutable": mutable,
                "path": entry["path"],
                "supporting_files": supporting or None,
            })
        return json.dumps({
            "success": True,
            "skills": results,
            "count": len(results),
            "hint": "Use skill_view(name) to see full content, or skill_manage to create/update skills.",
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SkillViewTool
# ---------------------------------------------------------------------------


@tool_parameters({
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The skill name (use skills_list to see available skills).",
        },
        "file_path": {
            "type": "string",
            "description": (
                "Optional path to a supporting file within the skill "
                "(e.g. 'references/api.md', 'templates/config.yaml'). "
                "Omit to get the main SKILL.md content."
            ),
        },
    },
    "required": ["name"],
})
class SkillViewTool(Tool):
    """View a skill's full content or a specific supporting file."""

    def __init__(self, catalog: SkillsLoader, store: Any = None) -> None:
        self._catalog = catalog
        self._store = store

    @property
    def name(self) -> str:
        return "skill_view"

    @property
    def description(self) -> str:
        return (
            "Load a skill's full content or access its supporting files "
            "(references, templates, scripts, assets). "
            "Use skills_list first to see available skills."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        skill_name: str = kwargs.get("name", "")
        file_path: str | None = kwargs.get("file_path")

        if not skill_name:
            return json.dumps({"success": False, "error": "name is required."}, ensure_ascii=False)

        result = self._catalog.find_skill_dir(skill_name)
        if result is None:
            available = [e["name"] for e in self._catalog.list_skills(filter_unavailable=False)[:20]]
            return json.dumps({
                "success": False,
                "error": f"Skill '{skill_name}' not found.",
                "available_skills": available,
            }, ensure_ascii=False)

        skill_dir, source = result

        if file_path:
            content = self._catalog.load_skill_file(skill_name, file_path)
            if content is None:
                supporting = self._catalog.list_supporting_files(skill_name)
                return json.dumps({
                    "success": False,
                    "error": f"File '{file_path}' not found or not accessible in skill '{skill_name}'.",
                    "available_files": supporting or None,
                    "hint": "File must be under references/, templates/, scripts/, or assets/.",
                }, ensure_ascii=False)
            return json.dumps({
                "success": True,
                "name": skill_name,
                "file": file_path,
                "content": content,
            }, ensure_ascii=False)

        # Return main SKILL.md
        content = self._catalog.load_skill(skill_name)
        if content is None:
            return json.dumps({"success": False, "error": f"Failed to read skill '{skill_name}'."}, ensure_ascii=False)

        if self._store is not None:
            try:
                self._store.record_usage(skill_name)
            except Exception:
                pass

        metadata = self._catalog.get_skill_metadata(skill_name) or {}
        supporting = self._catalog.list_supporting_files(skill_name)

        return json.dumps({
            "success": True,
            "name": skill_name,
            "description": metadata.get("description", ""),
            "source": source,
            "mutable": source == "workspace",
            "content": content,
            "linked_files": supporting or None,
            "usage_hint": (
                "To view linked files, call skill_view(name, file_path) "
                "where file_path is e.g. 'references/api.md'"
            ) if supporting else None,
        }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SkillManageTool (registered in Phase 2)
# ---------------------------------------------------------------------------


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["create", "edit", "patch", "delete", "write_file", "remove_file"],
            "description": "The action to perform.",
        },
        "name": {
            "type": "string",
            "description": "Skill name (lowercase, hyphens/underscores, max 64 chars).",
        },
        "content": {
            "type": "string",
            "description": (
                "Full SKILL.md content (YAML frontmatter + markdown body). "
                "Required for 'create' and 'edit'."
            ),
        },
        "old_string": {
            "type": "string",
            "description": "Text to find in the file (required for 'patch').",
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text (required for 'patch'). Empty string to delete.",
        },
        "replace_all": {
            "type": "boolean",
            "description": "For 'patch': replace all occurrences (default: false).",
        },
        "file_path": {
            "type": "string",
            "description": (
                "Path to a supporting file within the skill directory. "
                "Required for 'write_file'/'remove_file'. "
                "Must be under references/, templates/, scripts/, or assets/."
            ),
        },
        "file_content": {
            "type": "string",
            "description": "Content for the file. Required for 'write_file'.",
        },
    },
    "required": ["action", "name"],
})
class SkillManageTool(Tool):
    """Create, update, and delete skills — the agent's procedural memory."""

    def __init__(
        self,
        store: SkillStore,
        catalog: SkillsLoader,
        config: SkillsConfig,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._config = config

    @property
    def name(self) -> str:
        return "skill_manage"

    @property
    def description(self) -> str:
        return (
            "Manage skills (create, update, delete). Skills are your procedural "
            "memory — reusable approaches for recurring task types.\n\n"
            "Actions: create (full SKILL.md), "
            "patch (old_string/new_string — preferred for fixes), "
            "edit (full SKILL.md rewrite — major overhauls only), "
            "delete, write_file, remove_file.\n\n"
            "Create when: complex task succeeded (5+ tool calls), errors overcome, "
            "user-corrected approach worked, non-trivial workflow discovered.\n"
            "Update when: instructions stale/wrong, missing steps or pitfalls "
            "found during use.\n\n"
            "Good skills: trigger conditions, numbered steps with exact commands, "
            "pitfalls section, verification steps."
        )

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        skill_name = kwargs.get("name", "")

        if action == "create":
            if not self._config.allow_create:
                return json.dumps({"success": False, "error": "Skill creation is disabled by configuration."})
            content = kwargs.get("content")
            if not content:
                return json.dumps({"success": False, "error": "content is required for 'create'."})
            return json.dumps(self._store.create_skill(skill_name, content), ensure_ascii=False)

        if action == "edit":
            if not self._config.allow_patch:
                return json.dumps({"success": False, "error": "Skill editing is disabled by configuration."})
            content = kwargs.get("content")
            if not content:
                return json.dumps({"success": False, "error": "content is required for 'edit'."})
            return json.dumps(self._store.edit_skill(skill_name, content), ensure_ascii=False)

        if action == "patch":
            if not self._config.allow_patch:
                return json.dumps({"success": False, "error": "Skill patching is disabled by configuration."})
            old_string = kwargs.get("old_string")
            new_string = kwargs.get("new_string")
            if not old_string:
                return json.dumps({"success": False, "error": "old_string is required for 'patch'."})
            if new_string is None:
                return json.dumps({"success": False, "error": "new_string is required for 'patch'."})
            return json.dumps(self._store.patch_skill(
                skill_name, old_string, new_string,
                file_path=kwargs.get("file_path"),
                replace_all=kwargs.get("replace_all", False),
            ), ensure_ascii=False)

        if action == "delete":
            if not self._config.allow_delete:
                return json.dumps({"success": False, "error": "Skill deletion is disabled by configuration."})
            return json.dumps(self._store.delete_skill(skill_name), ensure_ascii=False)

        if action == "write_file":
            file_path = kwargs.get("file_path")
            file_content = kwargs.get("file_content")
            if not file_path:
                return json.dumps({"success": False, "error": "file_path is required for 'write_file'."})
            if file_content is None:
                return json.dumps({"success": False, "error": "file_content is required for 'write_file'."})
            return json.dumps(self._store.write_file(skill_name, file_path, file_content), ensure_ascii=False)

        if action == "remove_file":
            file_path = kwargs.get("file_path")
            if not file_path:
                return json.dumps({"success": False, "error": "file_path is required for 'remove_file'."})
            return json.dumps(self._store.remove_file(skill_name, file_path), ensure_ascii=False)

        return json.dumps({
            "success": False,
            "error": f"Unknown action '{action}'. Use: create, edit, patch, delete, write_file, remove_file",
        })
