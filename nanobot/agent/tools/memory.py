"""Memory recall tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool


class MemorySearchTool(Tool):
    """Search compact and archival memory documents."""

    def __init__(self, workspace: Path):
        self._store = MemoryStore(workspace)

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Search long-term memory and dated memory notes. Use this instead of relying on archive memory being auto-injected."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query for memory recall.",
                    "minLength": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, limit: int = 5, **kwargs: Any) -> str:
        results = self._store.search(query, limit=limit)
        if not results:
            return "No matching memory found."
        return json.dumps(results, ensure_ascii=False, indent=2)


class MemoryGetTool(Tool):
    """Read a specific memory document."""

    def __init__(self, workspace: Path):
        self._store = MemoryStore(workspace)

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Read a specific file inside the workspace memory directory, such as memory/2026-03-09.md."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Memory document path, usually relative to the workspace like memory/2026-03-09.md.",
                    "minLength": 1,
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            return self._store.get_document(path)
        except PermissionError as exc:
            return f"Error: {exc}"
        except FileNotFoundError as exc:
            return f"Error: {exc}"
