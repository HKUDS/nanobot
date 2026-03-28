"""MemorySearchTool — semantic search over indexed memory files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.memory_index.index import MemoryIndex


class MemorySearchTool(Tool):
    """Search long-term memory and conversation history semantically."""

    def __init__(self, index: MemoryIndex) -> None:
        self.index = index

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search long-term memory and conversation history semantically. "
            "Use when recalling facts, preferences, or past context that may "
            "not be in the current session."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, top_k: int = 5, **kwargs: Any) -> str:
        results = await self.index.search(query, top_k=top_k)
        if not results:
            return "No relevant memory found."
        return "\n\n---\n\n".join(
            f"[{r.source} L{r.start_line}–{r.end_line}]\n{r.text}" for r in results
        )
