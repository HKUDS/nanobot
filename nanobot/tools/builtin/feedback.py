"""Feedback tool — captures explicit user feedback on answers."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from nanobot.tools.base import Tool, ToolResult


class FeedbackTool(Tool):
    """Tool the agent can call to record user feedback (thumbs-up/down + optional text).

    Feedback events are persisted into ``events.jsonl`` so that later
    memory consolidation passes can down-weight memories associated with
    corrected answers and surface correction statistics.
    """

    readonly = False  # mutates persistent state

    def __init__(self, events_file: Path | None = None):
        self._events_file = events_file
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
        events_file: Path | None = kwargs.get("events_file")
        if events_file is not None:
            self._events_file = events_file

    def _write_event(self, event: dict[str, Any]) -> None:
        """Blocking write — called via asyncio.to_thread."""
        if self._events_file is None:
            return
        self._events_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

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

        event = {
            "id": f"fb-{uuid.uuid4().hex[:12]}",
            "type": "feedback",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating,
            "channel": self._channel,
            "chat_id": self._chat_id,
            "session_key": self._session_key,
        }
        if comment:
            event["comment"] = comment
        if topic:
            event["topic"] = topic

        # Persist to events.jsonl (offloaded to thread to avoid blocking the event loop)
        if self._events_file is not None:
            try:
                await asyncio.to_thread(self._write_event, event)
            except OSError as exc:
                return ToolResult.fail(f"Failed to persist feedback: {exc}")

        label = f"{rating}"
        if topic:
            label += f" on '{topic}'"
        if comment:
            label += f" — {comment[:80]}"
        return ToolResult.ok(f"Feedback recorded: {label}")
