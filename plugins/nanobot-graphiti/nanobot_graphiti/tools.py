"""Memory tools for the Graphiti memory backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot_graphiti.backend import GraphitiMemoryBackend


class MemorySearchTool(Tool):
    """Semantic search over the Graphiti memory graph."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search your memory for facts about the current user. "
            "Use when asked about past conversations, preferences, or history."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "top_k": {"type": "integer", "description": "Max results to return", "default": 10},
                "session_key": {"type": "string", "description": "Current session key (e.g. telegram:123456)"},
            },
            "required": ["query", "session_key"],
        }

    async def execute(self, query: str, session_key: str, top_k: int = 10, **_: Any) -> str:
        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        group_id = self._backend._get_group_id(session_key)
        results = await graphiti.search(query, group_ids=[group_id], num_results=top_k)
        if not results:
            return f"No memories found for query: {query!r}"
        lines = [f"Found {len(results)} fact(s):"]
        for edge in results:
            lines.append(f"• [{edge.uuid}] {edge.fact}")
        return "\n".join(lines)


class MemoryForgetTool(Tool):
    """Delete a specific fact from the memory graph by its ID."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_forget"

    @property
    def description(self) -> str:
        return (
            "Delete a specific memory fact by its ID. "
            "Use when a user says 'you have that wrong' or asks you to forget something. "
            "Get the fact_id from memory_search or memory_list first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "The UUID of the fact to delete"},
                "reason": {"type": "string", "description": "Why this fact is being removed"},
                "session_key": {"type": "string", "description": "Current session key"},
            },
            "required": ["fact_id", "reason", "session_key"],
        }

    async def execute(self, fact_id: str, reason: str, session_key: str, **_: Any) -> str:
        from graphiti_core.nodes import EntityEdge

        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        group_id = self._backend._get_group_id(session_key)
        # Verify ownership: ensure fact_id belongs to this session's group
        results = await graphiti.search(fact_id, group_ids=[group_id], num_results=50)
        owned = any(e.uuid == fact_id for e in results)
        if not owned:
            return f"Fact {fact_id!r} not found in your memory."
        await EntityEdge.delete_by_uuids(graphiti.driver, [fact_id])
        return f"Fact {fact_id!r} deleted. Reason: {reason}"


class MemoryListTool(Tool):
    """List all stored memory facts for the current user."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return (
            "List all stored memory facts for the current user. "
            "Use when asked 'what do you know about me?' or to audit stored memories."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max facts to return", "default": 50},
                "session_key": {"type": "string", "description": "Current session key"},
            },
            "required": ["session_key"],
        }

    async def execute(self, session_key: str, limit: int = 50, **_: Any) -> str:
        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        group_id = self._backend._get_group_id(session_key)
        results = await graphiti.search("", group_ids=[group_id], num_results=limit)
        if not results:
            return "No memories stored for this user."
        lines = [f"Stored memories ({len(results)} fact(s)):"]
        for edge in results:
            lines.append(f"• [{edge.uuid}] {edge.fact}")
        return "\n".join(lines)
