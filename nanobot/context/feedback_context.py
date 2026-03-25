"""Feedback context — summarise user feedback for system-prompt injection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
