"""Search raw L0 conversation messages (LM2-E)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.search_format import format_conversation_search_results
from nanobot.agent.layered_memory.tool_support import (
    capture_tools_enabled,
    consume_search_budget,
    session_key_from_request,
)
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from nanobot.agent.tools.schema import BooleanSchema, IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.schema import LayeredMemoryConfig


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema(
            "Keywords to search past conversation messages captured in layered memory (L0).",
            min_length=1,
        ),
        limit=IntegerSchema(
            8,
            description="Maximum number of messages to return (default 8)",
            minimum=1,
            maximum=30,
        ),
        session_only=BooleanSchema(
            default=True,
            description="When true (default), search only the current session",
        ),
        required=["query"],
    )
)
class ConversationSearchTool(Tool, ContextAware):
    """Substring search over ``l0_messages``."""

    _scopes = {"core"}

    def __init__(self, workspace: Path, layered_memory: LayeredMemoryConfig) -> None:
        self._workspace = workspace
        self._layered_memory = layered_memory
        self._l0_store = L0Store(workspace)
        self._request_ctx: RequestContext | None = None

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return capture_tools_enabled(ctx)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        layered = ctx.layered_memory or LayeredMemoryConfig()
        return cls(workspace=Path(ctx.workspace), layered_memory=layered)

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx = ctx

    @property
    def name(self) -> str:
        return "conversation_search"

    @property
    def description(self) -> str:
        return (
            "Search raw past dialogue snippets stored in layered memory (L0). "
            "Use to recover exact wording from earlier turns; not for tool output files."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        query: str | None = None,
        limit: int = 8,
        session_only: bool = True,
        **kwargs: Any,
    ) -> str:
        if not query or not str(query).strip():
            return "Error: query is required"
        session_key = session_key_from_request(self._request_ctx)
        if session_only and not session_key:
            return "Error: no active session context for conversation_search"

        budget_err = consume_search_budget(self._layered_memory)
        if budget_err:
            return budget_err

        scope_key = session_key if session_only else None
        hits = self._l0_store.search_messages(
            str(query).strip(),
            session_key=scope_key,
            limit=min(max(1, limit), 30),
        )
        logger.info(
            "layered_memory conversation_search session={} query={!r} hits={} session_only={}",
            session_key or "-",
            query,
            len(hits),
            session_only,
        )
        return format_conversation_search_results(str(query).strip(), hits)
