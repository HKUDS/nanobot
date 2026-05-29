"""Search distilled L1 memory atoms (LM2-E)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.search_format import format_memory_search_results
from nanobot.agent.layered_memory.search_l1 import search_l1_memories
from nanobot.agent.layered_memory.tool_support import (
    capture_tools_enabled,
    consume_search_budget,
    session_key_from_request,
)
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.schema import LayeredMemoryConfig


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema(
            "Keywords to search distilled long-term memories (preferences, facts, rules).",
            min_length=1,
        ),
        limit=IntegerSchema(
            5,
            description="Maximum number of atoms to return (default 5)",
            minimum=1,
            maximum=20,
        ),
        required=["query"],
    )
)
class MemorySearchTool(Tool, ContextAware):
    """FTS search over ``l1_memories`` atoms."""

    _scopes = {"core"}

    def __init__(self, workspace: Path, layered_memory: LayeredMemoryConfig) -> None:
        self._workspace = workspace
        self._layered_memory = layered_memory
        self._l1_store = L1Store(workspace)
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
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search distilled long-term memory atoms (user preferences, facts, rules). "
            "Use for stable user-specific knowledge, not raw chat logs or tool output files."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        query: str | None = None,
        limit: int = 5,
        **kwargs: Any,
    ) -> str:
        if not query or not str(query).strip():
            return "Error: query is required"
        session_key = session_key_from_request(self._request_ctx)
        if not session_key:
            return "Error: no active session context for memory_search"

        budget_err = consume_search_budget(self._layered_memory)
        if budget_err:
            return budget_err

        recall_cfg = self._layered_memory.recall
        hits = search_l1_memories(
            self._l1_store,
            str(query).strip(),
            session_key,
            limit=min(max(1, limit), 20),
            strategy=recall_cfg.strategy,
        )
        logger.info(
            "layered_memory memory_search session={} query={!r} hits={}",
            session_key,
            query,
            len(hits),
        )
        return format_memory_search_results(str(query).strip(), hits)
