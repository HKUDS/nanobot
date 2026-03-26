"""Feedback context — summarise user feedback for system-prompt injection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.memory.unified_db import UnifiedMemoryDB


def _unpack_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata fields into the top-level event dict for uniform access."""
    meta = event.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    if isinstance(meta, dict):
        # Metadata fields (rating, comment, topic, etc.) become top-level.
        return {**event, **meta}
    return event


def load_feedback_events(db: UnifiedMemoryDB) -> list[dict[str, Any]]:
    """Load all feedback-type events from the database."""
    rows = db.read_events(type="feedback", limit=1000)
    return [_unpack_metadata(row) for row in rows]


def feedback_summary(db: UnifiedMemoryDB, *, max_recent: int = 20) -> str:
    """Build a concise summary of feedback events for system-prompt injection.

    Returns an empty string when there is no feedback to report.
    """
    items = load_feedback_events(db)
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
