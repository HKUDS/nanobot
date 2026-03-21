"""Shared pure-function utilities for the memory subsystem.

These were originally duplicated as static/class methods across
``MemoryStore``, ``ProfileManager``, ``ConflictManager``, and
``ContextAssembler``.  Centralising them here removes ~200 lines of
duplication and provides a single import target for all memory modules.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str_list(value: Any) -> list[str]:
    """Coerce *value* to a list of non-empty stripped strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _to_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string to *datetime*, returning ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------


def _norm_text(value: str) -> str:
    """Lowercase, strip, and collapse whitespace."""
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokenize(value: str) -> set[str]:
    """Split *value* into lowercased alphanumeric tokens (len > 1)."""
    return {t for t in re.findall(r"[a-zA-Z0-9_\-]+", value.lower()) if len(t) > 1}


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Rough token count approximation (1 token ~ 4 chars)."""
    value = str(text or "")
    if not value:
        return 0
    return max(1, len(value) // 4)


# ---------------------------------------------------------------------------
# Substring matching
# ---------------------------------------------------------------------------


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """Return ``True`` if *text* contains any of the *needles* (case-insensitive)."""
    lowered = str(text or "").lower()
    return any(needle in lowered for needle in needles)


# ---------------------------------------------------------------------------
# Graph query keyword extraction
# ---------------------------------------------------------------------------

_GRAPH_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "this",
        "that",
        "then",
        "than",
        "they",
        "them",
        "there",
        "these",
        "those",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "also",
        "and",
        "but",
        "for",
        "from",
        "into",
        "just",
        "like",
        "not",
        "only",
        "some",
        "such",
        "very",
        "will",
        "with",
        "would",
        "could",
        "should",
        "about",
        "after",
        "before",
        "been",
        "being",
        "have",
        "here",
        "more",
        "most",
        "much",
        "over",
        "same",
        "still",
        "each",
        "even",
        "every",
        "other",
        "are",
        "was",
        "were",
        "had",
        "has",
        "does",
        "did",
        "any",
        "its",
        "can",
        "may",
        "is",
        "it",
        "an",
        "or",
        "no",
        "do",
        "so",
        "if",
        "my",
        "me",
        "his",
        "her",
        "our",
        "your",
        "their",
        "a",
        "of",
        "in",
        "on",
        "to",
        "at",
        "by",
        "currently",
        "involved",
        "caused",
        "resolved",
        "apply",
    }
)


def _extract_query_keywords(query: str) -> set[str]:
    """Extract significant keywords from a query for graph entity lookup."""
    tokens = {t for t in re.findall(r"[a-zA-Z0-9_\-]+", query.lower()) if len(t) > 2}
    return tokens - _GRAPH_QUERY_STOPWORDS
