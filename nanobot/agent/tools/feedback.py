"""Feedback tool — captures explicit user feedback on answers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult


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
        channel: str,
        chat_id: str,
        *,
        session_key: str = "",
        events_file: Path | None = None,
    ) -> None:
        self._channel = channel
        self._chat_id = chat_id
        self._session_key = session_key or f"{channel}:{chat_id}"
        if events_file is not None:
            self._events_file = events_file

    # ------------------------------------------------------------------
    # Tool schema
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "feedback"

    @property
    def description(self) -> str:
        return (
            "Record user feedback on an answer or interaction. "
            "Use this when the user explicitly expresses satisfaction or dissatisfaction, "
            "gives a correction, or reacts with thumbs-up/down. "
            "rating: 'positive' or 'negative'. "
            "comment: optional free-text with the user's correction or remark."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
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

        # Persist to events.jsonl
        if self._events_file is not None:
            try:
                self._events_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._events_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as exc:
                return ToolResult.fail(f"Failed to persist feedback: {exc}")

        label = f"{rating}"
        if topic:
            label += f" on '{topic}'"
        if comment:
            label += f" — {comment[:80]}"
        return ToolResult.ok(f"Feedback recorded: {label}")


# ---------------------------------------------------------------------------
# Helpers for reading feedback from events.jsonl
# ---------------------------------------------------------------------------


def load_feedback_events(events_file: Path) -> list[dict[str, Any]]:
    """Load all feedback-type events from the events file."""
    if not events_file.exists():
        return []
    items: list[dict[str, Any]] = []
    with open(events_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("type") == "feedback":
                items.append(obj)
    return items


def feedback_summary(events_file: Path, *, max_recent: int = 20) -> str:
    """Build a concise summary of feedback events for system-prompt injection.

    Returns an empty string when there is no feedback to report.
    """
    items = load_feedback_events(events_file)
    if not items:
        return ""

    positive = sum(1 for e in items if e.get("rating") == "positive")
    negative = sum(1 for e in items if e.get("rating") == "negative")
    total = len(items)

    parts: list[str] = [f"User feedback: {positive} positive, {negative} negative ({total} total)."]

    # Collect recent negative items with comments (most actionable)
    negatives_with_comment = [
        e for e in items if e.get("rating") == "negative" and e.get("comment")
    ]
    recent_neg = negatives_with_comment[-max_recent:]
    if recent_neg:
        parts.append("Recent corrections/complaints:")
        for ev in recent_neg:
            topic = ev.get("topic", "")
            comment = ev.get("comment", "")
            line = f"  - {topic}: {comment}" if topic else f"  - {comment}"
            parts.append(line)

    # Topic frequency for negative feedback
    topic_counts: dict[str, int] = {}
    for e in items:
        if e.get("rating") == "negative" and e.get("topic"):
            t = e["topic"]
            topic_counts[t] = topic_counts.get(t, 0) + 1
    if topic_counts:
        worst = sorted(topic_counts.items(), key=lambda x: -x[1])[:5]
        summary_line = ", ".join(f"{t} ({c}x)" for t, c in worst)
        parts.append(f"Most corrected topics: {summary_line}")

    return "\n".join(parts)
