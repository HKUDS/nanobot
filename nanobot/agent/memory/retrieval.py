"""Local keyword-based event retrieval (fallback when mem0 is unavailable).

This module provides a lightweight retrieval path that does not require
any external vector store.  It tokenizes queries and stored events into
lowercase alphanumeric tokens and scores candidates via token overlap,
recency decay, and salience weighting.

Used by ``MemoryStore`` as the fallback retrieval strategy when mem0 is
not configured or unhealthy, and also as the candidate generator before
optional cross-encoder re-ranking.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


def _tokenize_for_search(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (>=2 chars) for keyword overlap scoring."""
    return {t for t in re.findall(r"[a-z0-9_\-]+", text.lower()) if len(t) >= 2}


def _keyword_score(query_tokens: set[str], event: dict[str, Any]) -> float:
    """Score an event against a query using token overlap on summary + entities.

    Returns a value in [0, 1].
    """
    summary = str(event.get("summary", ""))
    entities = " ".join(str(e) for e in event.get("entities", []) if isinstance(e, str))
    event_tokens = _tokenize_for_search(f"{summary} {entities}")
    if not query_tokens or not event_tokens:
        return 0.0
    overlap = len(query_tokens & event_tokens)
    return overlap / max(len(query_tokens), 1)


def _local_retrieve(
    events: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = 6,
    recency_half_life_days: float | None = None,
) -> list[dict[str, Any]]:
    """Retrieve events from a list using keyword overlap scoring.

    Optionally applies exponential recency decay.
    """
    query_tokens = _tokenize_for_search(query)
    if not query_tokens:
        return []

    now = datetime.now(timezone.utc)
    scored: list[tuple[float, dict[str, Any]]] = []

    for event in events:
        if str(event.get("status", "")).lower() == "superseded":
            continue
        score = _keyword_score(query_tokens, event)
        if score <= 0:
            continue

        # Optional recency boost
        if recency_half_life_days and recency_half_life_days > 0:
            ts_str = str(event.get("timestamp", ""))
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                days_old = max((now - ts).total_seconds() / 86400, 0)
                decay = math.exp(-0.693 * days_old / recency_half_life_days)
                score *= 0.5 + 0.5 * decay
            except (ValueError, TypeError):
                pass

        scored.append((score, event))

    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, event in scored[:top_k]:
        result = dict(event)
        result["retrieval_reason"] = {
            "provider": "keyword",
            "backend": "jsonl",
            "score": round(score, 4),
        }
        result["provenance"] = {
            "canonical_id": str(event.get("canonical_id", event.get("id", ""))),
            "evidence_count": max(int(event.get("merged_event_count", 1)), 1),
        }
        results.append(result)
    return results
