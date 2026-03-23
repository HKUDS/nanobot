"""Local keyword-based event retrieval (fallback when mem0 is unavailable).

This module provides a lightweight retrieval path that does not require
any external vector store.  It tokenizes queries and stored events into
lowercase alphanumeric tokens and scores candidates via BM25 ranking,
recency decay, and salience weighting.

Used by ``MemoryStore`` as the fallback retrieval strategy when mem0 is
not configured or unhealthy, and also as the candidate generator for
hybrid retrieval alongside vector search.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Synonym normalization — applied at index & query time so morphological
# variants match correctly without requiring an embedding model.
# ---------------------------------------------------------------------------
_SYNONYM_MAP: dict[str, str] = {
    "failed": "fail",
    "failure": "fail",
    "failing": "fail",
    "constraints": "constraint",
    "resolved": "resolve",
    "resolving": "resolve",
    "completed": "complete",
    "completing": "complete",
    "closed": "close",
    "closing": "close",
    "learned": "learn",
    "learning": "learn",
    "lessons": "lesson",
    "updates": "update",
    "updated": "update",
    "corrected": "correct",
    "correction": "correct",
    "corrections": "correct",
    "preferences": "preference",
    "preferred": "prefer",
    "prefers": "prefer",
    "incidents": "incident",
    "decisions": "decision",
    "tasks": "task",
    "reflections": "reflection",
    "reflect": "reflection",
    "relationships": "relationship",
    "collaborator": "relationship",
    "collaborators": "relationship",
    "superseded": "supersede",
    "stale": "supersede",
    "enabled": "enable",
    "disabled": "disable",
    "tried": "try",
    "tries": "try",
    "trying": "try",
    "persisted": "persist",
    "persisting": "persist",
    "steps": "step",
    "projects": "project",
    "memories": "memory",
}


def _tokenize_for_search(text: str) -> list[str]:
    """Lowercase alphanumeric tokens (>=2 chars) with synonym normalization.

    Splits on non-alphanumeric characters so compound terms like
    "task_progress" and "eu-west-1" become separate tokens.
    """
    raw = re.findall(r"[a-z0-9]+", text.lower())
    return [_SYNONYM_MAP.get(t, t) for t in raw if len(t) >= 2]


def _tokenize_set(text: str) -> set[str]:
    """Convenience: unique tokens for overlap scoring."""
    return set(_tokenize_for_search(text))


# ---------------------------------------------------------------------------
# BM25 scoring (Okapi BM25)
# ---------------------------------------------------------------------------
_BM25_K1 = 1.5
_BM25_B = 0.75


def _build_bm25_index(
    events: list[dict[str, Any]],
) -> tuple[list[list[str]], dict[str, int], float]:
    """Build per-document token lists, document-frequency map, and avg doc length.

    Returns (doc_tokens_list, df_map, avg_dl).
    """
    doc_tokens_list: list[list[str]] = []
    df: dict[str, int] = {}
    total_len = 0

    for event in events:
        summary = str(event.get("summary", ""))
        entities = " ".join(str(e) for e in event.get("entities", []) if isinstance(e, str))
        meta = event.get("metadata", {})
        ev_type = str(event.get("type", ""))
        topic = str(meta.get("topic", ""))
        memory_type = str(meta.get("memory_type", ""))
        status = str(event.get("status", ""))
        tokens = _tokenize_for_search(
            f"{summary} {entities} {ev_type} {topic} {memory_type} {status}"
        )
        doc_tokens_list.append(tokens)
        total_len += len(tokens)
        seen: set[str] = set()
        for t in tokens:
            if t not in seen:
                df[t] = df.get(t, 0) + 1
                seen.add(t)

    n = len(events)
    avg_dl = total_len / n if n > 0 else 1.0
    return doc_tokens_list, df, avg_dl


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    df: dict[str, int],
    n_docs: int,
    avg_dl: float,
) -> float:
    """Compute Okapi BM25 score for a single document against a query."""
    if not query_tokens or not doc_tokens:
        return 0.0

    dl = len(doc_tokens)
    # Term frequency in document
    tf_map: dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    score = 0.0
    for qt in query_tokens:
        if qt not in tf_map:
            continue
        tf = tf_map[qt]
        doc_freq = df.get(qt, 0)
        # IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        idf = math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
        # BM25 TF component
        numerator = tf * (_BM25_K1 + 1)
        denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg_dl)
        score += idf * numerator / denominator

    return score


def _keyword_score(query_tokens: set[str], event: dict[str, Any]) -> float:
    """Score an event against a query using token overlap on summary + entities.

    Returns a value in [0, 1].  Kept for backward compatibility.
    """
    summary = str(event.get("summary", ""))
    entities = " ".join(str(e) for e in event.get("entities", []) if isinstance(e, str))
    event_tokens = _tokenize_set(f"{summary} {entities}")
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
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve events from a list using BM25 ranking.

    Optionally applies exponential recency decay.
    """
    query_tokens = _tokenize_for_search(query)
    if not query_tokens:
        return []

    # Filter out superseded events before indexing (unless explicitly requested).
    if include_superseded:
        active_events = list(events)
    else:
        active_events = [e for e in events if str(e.get("status", "")).lower() != "superseded"]
    if not active_events:
        return []

    # Build BM25 index over active events.
    doc_tokens_list, df, avg_dl = _build_bm25_index(active_events)
    n_docs = len(active_events)

    now = datetime.now(timezone.utc)
    scored: list[tuple[float, dict[str, Any]]] = []

    for idx, event in enumerate(active_events):
        score = _bm25_score(query_tokens, doc_tokens_list[idx], df, n_docs, avg_dl)
        if score <= 0:
            continue

        # Normalize BM25 score to roughly [0, 1] range for compatibility.
        # Max theoretical BM25 per query term ≈ idf * (k1+1) ≈ 3.5 * 2.5 = 8.75
        # With typical queries of 3-6 terms, raw scores can reach ~30.
        # Sigmoid normalization keeps scores bounded and monotonic.
        score = 1.0 / (1.0 + math.exp(-0.3 * (score - 3.0)))

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
            "provider": "bm25",
            "backend": "jsonl",
            "score": round(score, 4),
        }
        result["provenance"] = {
            "canonical_id": str(event.get("canonical_id", event.get("id", ""))),
            "evidence_count": max(int(event.get("merged_event_count", 1)), 1),
        }
        results.append(result)
    return results


def _topic_fallback_retrieve(
    events: list[dict[str, Any]],
    *,
    target_topics: list[str],
    target_memory_types: list[str],
    exclude_ids: set[str],
    top_k: int = 6,
    base_score: float = 0.25,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve events by metadata topic/memory_type match (no lexical overlap needed).

    Used as a fallback when BM25 returns too few candidates for categorical queries.
    """
    results: list[dict[str, Any]] = []
    topic_set = set(target_topics)
    mtype_set = set(target_memory_types)

    for event in events:
        eid = str(event.get("id", ""))
        if eid in exclude_ids:
            continue
        if not include_superseded and str(event.get("status", "")).lower() == "superseded":
            continue

        meta = event.get("metadata", {})
        topic = str(meta.get("topic", ""))
        memory_type = str(meta.get("memory_type", ""))

        if topic in topic_set or memory_type in mtype_set:
            result = dict(event)
            result["retrieval_reason"] = {
                "provider": "topic_fallback",
                "backend": "jsonl",
                "score": round(base_score, 4),
            }
            result["provenance"] = {
                "canonical_id": str(event.get("canonical_id", event.get("id", ""))),
                "evidence_count": max(int(event.get("merged_event_count", 1)), 1),
            }
            results.append(result)
            if len(results) >= top_k:
                break

    return results
