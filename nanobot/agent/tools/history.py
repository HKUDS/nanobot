"""Read-only tool for searching the agent's own conversation history."""
from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.utils.helpers import truncate_text

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
_PER_ENTRY_CHARS = 1000


@tool_parameters(tool_parameters_schema(
    query=StringSchema(
        "Case-insensitive substring to match against past entries. "
        "Omit to return the most recent entries.",
        nullable=True,
    ),
    limit=IntegerSchema(
        description=(
            f"Maximum number of entries to return (1-{_MAX_LIMIT}, "
            f"default {_DEFAULT_LIMIT})."
        ),
        minimum=1,
        maximum=_MAX_LIMIT,
        nullable=True,
    ),
))
class SearchHistoryTool(Tool):
    """Search the agent's long-term conversation history (``memory/history.jsonl``).

    History is an append-only log of consolidated summaries that is *not* kept
    in the active context window. Compared with grepping the raw JSONL, this
    tool returns parsed, validated, length-capped entries: the model never has
    to parse JSON itself, and malformed rows are dropped rather than surfaced.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "search_history"

    @property
    def description(self) -> str:
        return (
            "Search your own long-term conversation history for past entries. "
            "History holds consolidated summaries of earlier conversations that "
            "are no longer in the active context window. Use it to recall prior "
            "decisions, facts, or discussions. Returns matching entries "
            "newest-first; omit `query` to get the most recent entries."
        )

    @property
    def read_only(self) -> bool:
        return True

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return getattr(ctx, "memory_store", None) is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(store=ctx.memory_store)

    async def execute(
        self,
        query: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> str:
        n = limit if limit is not None else _DEFAULT_LIMIT
        entries = self._store.search_history(query, limit=n)
        if not entries:
            if query:
                return f"No history entries matching {query!r}."
            return "No conversation history recorded yet."
        lines = [
            f"[{e['timestamp']}] {truncate_text(e['content'], _PER_ENTRY_CHARS)}"
            for e in entries
        ]
        count = len(entries)
        noun = "entry" if count == 1 else "entries"
        header = f"{count} matching {noun} (newest first):"
        return header + "\n" + "\n".join(lines)
