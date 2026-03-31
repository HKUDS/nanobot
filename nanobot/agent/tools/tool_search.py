"""Tool for discovering available tools by intent keywords."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry


class ToolSearchTool(Tool):
    """Search available tools by name/description keywords."""

    name = "tool_search"
    description = "Find the best tool to use for a task."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Task intent or keywords"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of tools to return (1-20)",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    }

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        q = (query or "").strip().lower()
        if not q:
            return "Error: query is required"

        tokens = [t for t in re.split(r"[^a-z0-9_]+", q) if t]
        tool_defs = self.registry.get_definitions()
        matches: list[tuple[int, str, str]] = []

        for item in tool_defs:
            fn = item.get("function", {})
            name = str(fn.get("name", ""))
            if name == self.name:
                continue
            desc = str(fn.get("description", ""))
            haystack = f"{name} {desc}".lower()
            score = self._score(haystack, name.lower(), q, tokens)
            if score > 0:
                matches.append((score, name, desc))

        if not matches:
            return (
                f"No matching tools found for '{query}'. "
                "Try broader intent words like 'read file', 'search web', 'run command'."
            )

        matches.sort(key=lambda x: (-x[0], x[1]))
        n = min(max_results, 20)
        lines = [f"Top tools for '{query}':"]
        for i, (_, name, desc) in enumerate(matches[:n], 1):
            lines.append(f"{i}. {name} - {desc}")
        return "\n".join(lines)

    @staticmethod
    def _score(haystack: str, name: str, query: str, tokens: list[str]) -> int:
        score = 0
        if query in haystack:
            score += 6
        if query == name:
            score += 8
        if query in name:
            score += 4
        for token in tokens:
            if token in haystack:
                score += 2
            if token in name:
                score += 1
        return score
