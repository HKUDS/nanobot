"""Memory search tool for the agent."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.memory import MemoryStore


class MemorySearchTool(Tool):
    """Search memory files (MEMORY.md and daily notes) by keyword or semantics."""

    def __init__(self, memory_store: MemoryStore, max_results: int = 5):
        self._store = memory_store
        self._max_results = max_results

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search long-term memory and daily notes. "
            "Use this to find past preferences, facts, decisions, or context "
            "before writing new memories (to avoid duplicates) or when you need "
            "to recall something from a previous session."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords or natural language)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default 5)",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int | None = None, **kwargs: Any) -> str:
        n = max_results or self._max_results
        results = await self._store.search(query, max_results=n)

        if not results:
            return f"No memories found for: {query}"

        lines = [f"Found {len(results)} result(s) for: {query}\n"]
        for i, r in enumerate(results, 1):
            # Show relative path if possible
            path = r.path
            loc = f"(lines {r.start_line}-{r.end_line})" if r.start_line != r.end_line else f"(line {r.start_line})"
            snippet = r.text[:300] + "..." if len(r.text) > 300 else r.text
            lines.append(f"{i}. [score: {r.score}] {path} {loc}")
            lines.append(f"   {snippet}")
        return "\n".join(lines)
