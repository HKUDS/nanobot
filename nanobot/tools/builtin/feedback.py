"""Feedback tool — captures explicit user feedback on answers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from nanobot.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from nanobot.memory.unified_db import UnifiedMemoryDB


class FeedbackTool(Tool):
    """Tool the agent can call to record user feedback (thumbs-up/down + optional text).

    Feedback events are persisted into the SQLite memory database so that
    memory consolidation passes can down-weight memories associated with
    corrected answers and surface correction statistics.
    """

    readonly = False  # mutates persistent state

    def __init__(self, db: UnifiedMemoryDB | None = None):
        self._db = db
        # Set by the agent loop before each turn
        self._channel: str = ""
        self._chat_id: str = ""
        self._session_key: str = ""

    # ------------------------------------------------------------------
    # Context injection (called by AgentLoop._set_tool_context)
    # ------------------------------------------------------------------

    def set_context(
        self,
        channel: str = "",
        chat_id: str = "",
        message_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._channel = channel
        self._chat_id = chat_id
        session_key: str = kwargs.get("session_key", "")
        self._session_key = session_key or f"{channel}:{chat_id}"

    # ------------------------------------------------------------------
    # Tool schema
    # ------------------------------------------------------------------

    name = "feedback"
    description = (
        "Record user feedback on an answer or interaction. "
        "Use this when the user explicitly expresses satisfaction or dissatisfaction, "
        "gives a correction, or reacts with thumbs-up/down. "
        "rating: 'positive' or 'negative'. "
        "comment: optional free-text with the user's correction or remark."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "rating": {
                "type": "string",
                "enum": ["positive", "negative"],
                "description": "Positive (thumbs-up) or negative (thumbs-down) rating.",
            },
            "comment": {
                "type": "string",
                "description": "Optional free-text with the user's correction or remark.",
            },
            "topic": {
                "type": "string",
                "description": "Brief topic or label for what the feedback is about.",
            },
        },
        "required": ["rating"],
    }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        rating = kwargs.get("rating", "")
        if rating not in ("positive", "negative"):
            return ToolResult.fail("rating must be 'positive' or 'negative'")

        comment = str(kwargs.get("comment", "")).strip()
        topic = str(kwargs.get("topic", "")).strip()

        # Build summary for the events table
        summary = rating
        if topic:
            summary += f" on '{topic}'"
        if comment:
            summary += f" — {comment[:80]}"

        metadata: dict[str, str] = {
            "rating": rating,
            "channel": self._channel,
            "chat_id": self._chat_id,
            "session_key": self._session_key,
        }
        if comment:
            metadata["comment"] = comment
        if topic:
            metadata["topic"] = topic

        event = {
            "id": f"fb-{uuid.uuid4().hex[:12]}",
            "type": "feedback",
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
        }

        # Persist to SQLite (single INSERT, fast enough for sync call)
        if self._db is not None:
            try:
                self._db.insert_event(event)
            except Exception as exc:  # crash-barrier: db write errors should not crash the agent
                return ToolResult.fail(f"Failed to persist feedback: {exc}")

        return ToolResult.ok(f"Feedback recorded: {summary}")
