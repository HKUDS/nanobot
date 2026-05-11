"""``recall_memory`` tool: agent-driven MGP recall.

The tool gives the agent explicit access to the governed long-term memory
store via ``mgp_client``. It is **only** registered when ``mgp.enabled=true``
(see ``AgentLoop.__init__``); when disabled the tool is absent from the
schema and the ``mgp-memory`` skill is suppressed so the LLM never sees a
phantom capability.

Routing context (channel / chat_id / session_key) is stored in
``ContextVar`` instances per the convention introduced in upstream
``ff8c28d``, so concurrent turns in unified-session mode don't leak state.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from nanobot.agent.mgp.models import RecallOutcome
    from nanobot.agent.mgp.sidecar import AsyncMGPSidecar


@tool_parameters(tool_parameters_schema(
    query=StringSchema(
        "Concise topic to recall about the current user. Use a topic, not a "
        "full question. Good: 'indentation preference'. Bad: 'what indentation "
        "do I prefer?'.",
    ),
    scope=StringSchema(
        "Memory scope. 'user' = user-specific facts (preferences, decisions); "
        "'agent' = stable facts about the bot itself; 'session' = current-session events.",
        enum=["user", "agent", "session"],
    ),
    limit=IntegerSchema(
        description="Maximum number of memories to return (1-20). Defaults to "
                    "the configured `recall_default_limit`.",
        minimum=1,
        maximum=20,
    ),
    types=ArraySchema(
        items=StringSchema(enum=["preference", "semantic_fact", "profile", "episodic_event"]),
        description="Optional filter by memory types.",
    ),
    required=["query"],
))
class MGPRecallTool(Tool):
    """Agent-callable tool that searches the MGP gateway for relevant memories."""

    @property
    def name(self) -> str:  # type: ignore[override]
        return "recall_memory"

    @property
    def description(self) -> str:  # type: ignore[override]
        return (
            "Search governed long-term memory for facts about the current user, "
            "learned across previous sessions and channels.\n\n"
            "Use this when:\n"
            "- User refers to past preferences/decisions (\"remember my...\", \"what did I say about...\")\n"
            "- You need cross-session context (something user told you before but not in current conversation)\n"
            "- User asks about something that should be in long-term memory but is missing from your system prompt\n\n"
            "Don't use this when:\n"
            "- Information is already in your system prompt (MEMORY.md / SOUL.md / USER.md / Recent History)\n"
            "- Question is about general world knowledge\n"
            "- Question concerns only the current conversation\n\n"
            "Returns a list of recalled memories as bullet points; each item includes its type and content."
        )

    @property
    def read_only(self) -> bool:  # type: ignore[override]
        return True

    def __init__(
        self,
        sidecar: "AsyncMGPSidecar",
        *,
        default_scope: str = "user",
        default_limit: int = 5,
    ) -> None:
        self.sidecar = sidecar
        self._default_scope = default_scope
        self._default_limit = default_limit
        # ContextVar matches the new tool-routing convention (upstream ff8c28d)
        # so concurrent turns (e.g. unified-session multi-channel) don't leak.
        self._channel: ContextVar[str | None] = ContextVar("mgp_recall_channel", default=None)
        self._chat_id: ContextVar[str | None] = ContextVar("mgp_recall_chat_id", default=None)
        self._session_key: ContextVar[str | None] = ContextVar("mgp_recall_session_key", default=None)
        self._sender_id: ContextVar[str | None] = ContextVar("mgp_recall_sender_id", default=None)

    def set_context(
        self,
        channel: str | None,
        chat_id: str | None,
        effective_key: str | None = None,
        *,
        sender_id: str | None = None,
    ) -> None:
        """Per-task routing context. Signature is a superset of :class:`SpawnTool`
        so the loop's existing spawn-branch dispatch handles us with no new code.

        ``sender_id`` is the per-message sender (e.g. group-chat member id).
        Without it, group-chat recalls all attribute to the same ``chat_id``
        — meaning every group member shares one MGP subject. Threading
        ``sender_id`` through gives each member their own user-scoped memory.
        """
        self._channel.set(channel)
        self._chat_id.set(chat_id)
        self._sender_id.set(sender_id)
        self._session_key.set(
            effective_key
            or (f"{channel}:{chat_id}" if channel and chat_id else None)
        )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        scope: str | None = None,
        limit: int | None = None,
        types: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        # Defer the import: AsyncMGPSidecar pulls mgp_client which is optional.
        from nanobot.agent.mgp.models import RecallIntent

        runtime = self.sidecar.build_runtime(
            channel=self._channel.get(),
            chat_id=self._chat_id.get(),
            session_key=self._session_key.get(),
            sender_id=self._sender_id.get(),
        )
        intent = RecallIntent(
            query=query,
            scope=scope or self._default_scope,
            limit=limit if limit is not None else self._default_limit,
            types=types,
        )
        outcome = await self.sidecar.recall(runtime, intent)
        return self._format(outcome)

    @staticmethod
    def _format(outcome: "RecallOutcome") -> str:
        """Render a :class:`RecallOutcome` for LLM consumption."""
        if outcome.degraded:
            return f"[recall_memory degraded: {outcome.error_code}]"
        if not outcome.results:
            return "(no memories found)"
        lines: list[str] = []
        for item in outcome.results:
            mem_type = item.memory.get("type", "memory")
            text = item.consumable_text
            if not text:
                content = item.memory.get("content")
                if isinstance(content, dict):
                    text = content.get("statement") or content.get("preference") or str(content)
                else:
                    text = str(content) if content is not None else ""
            lines.append(f"- [{mem_type}] {text}")
        return "\n".join(lines)
