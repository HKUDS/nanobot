"""recall_memory tool: agent-initiated retrieval from long-term memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.memory import MemoryStore
    from nanobot.providers.base import LLMProvider

_SHORT_MEMORY_THRESHOLD = 500


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("What you want to find in long-term memory", min_length=1),
        required=["query"],
    )
)
class RecallMemoryTool(Tool):
    """Search long-term memory for information relevant to a query."""

    name = "recall_memory"
    description = (
        "Search long-term memory for information relevant to a query. "
        "Use this tool when the conversation touches on topics that might be "
        "related to past interactions, user preferences, or knowledge you have "
        "previously stored. Returns the relevant memory sections verbatim."
    )

    def __init__(
        self,
        store: MemoryStore,
        provider: LLMProvider,
        model: str,
    ) -> None:
        self._store = store
        self._provider = provider
        self._model = model

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, query: str = "", **kwargs: Any) -> str:
        full_memory = self._store.read_memory()
        if not full_memory:
            return "No long-term memory stored yet."

        # Short memory: return directly without an LLM call.
        if len(full_memory) < _SHORT_MEMORY_THRESHOLD:
            return full_memory

        try:
            response = await self._provider.chat_with_retry(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": render_template(
                            "agent/recall_filter.md", strip=True,
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"## Query\n{query}\n\n"
                            f"## Memory Content\n{full_memory}"
                        ),
                    },
                ],
                tools=None,
                tool_choice=None,
                max_tokens=1024,
            )
            result = response.content or ""
            if not result.strip():
                return "(no relevant memory found)"
            return result
        except Exception:
            logger.warning("recall_memory LLM call failed, returning raw memory")
            return full_memory
