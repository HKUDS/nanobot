"""Memory tools for the agent: search and write."""

from typing import Any

from loguru import logger

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


class MemoryWriteTool(Tool):
    """Write memories with automatic deduplication and lifecycle management."""

    VALID_CATEGORIES = ("preference", "fact", "project", "decision")

    def __init__(
        self,
        memory_store: MemoryStore,
        provider: Any = None,
        model: str = "",
    ):
        self._store = memory_store
        self._provider = provider
        self._model = model

    @property
    def name(self) -> str:
        return "memory_write"

    @property
    def description(self) -> str:
        return (
            "Write a memory to long-term storage (MEMORY.md). "
            "Automatically checks for duplicates and conflicting entries. "
            "Use this instead of directly editing MEMORY.md."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update"],
                    "description": "Action to perform: 'add' a new memory or 'update' an existing one",
                },
                "text": {
                    "type": "string",
                    "description": "The memory content (without category tag)",
                    "minLength": 1,
                    "maxLength": 512,
                },
                "category": {
                    "type": "string",
                    "enum": list(self.VALID_CATEGORIES),
                    "description": "Category tag: preference, fact, project, or decision",
                },
                "old_text": {
                    "type": "string",
                    "description": "For 'update': the existing entry text to replace",
                },
            },
            "required": ["action", "text", "category"],
        }

    async def execute(
        self,
        action: str,
        text: str,
        category: str,
        old_text: str | None = None,
        **kwargs: Any,
    ) -> str:
        if category not in self.VALID_CATEGORIES:
            return f"Invalid category '{category}'. Must be one of: {', '.join(self.VALID_CATEGORIES)}"

        try:
            if action == "update" and old_text:
                # Explicit update: agent knows what to replace
                ok = self._store.update_entry(old_text, text, category)
                if ok:
                    return f"Updated memory: [{category}] {text}"
                return f"Could not find entry to update containing: {old_text}"

            # For "add" (and "update" without old_text): run dedup
            if self._provider:
                dedup = await self._store.deduplicate(
                    text, category, self._provider, self._model
                )
                if dedup.action == "noop":
                    return f"Memory already exists (skipped). Reason: {dedup.reason}"
                if dedup.action == "update" and dedup.update_target:
                    ok = self._store.update_entry(dedup.update_target, text, category)
                    if ok:
                        return (
                            f"Updated existing memory: [{category}] {text} "
                            f"(reason: {dedup.reason})"
                        )
                    # Fall through to add if update target not found
                    logger.warning(
                        f"Dedup suggested update but target not found: {dedup.update_target}"
                    )

            # Default: add new entry
            self._store.add_entry(text, category)
            return f"Saved new memory: [{category}] {text}"

        except ValueError as e:
            return f"Memory write failed: {e}"
