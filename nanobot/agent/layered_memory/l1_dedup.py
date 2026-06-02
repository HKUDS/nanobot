"""L1 atom deduplication helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

_WS_RE = re.compile(r"\s+")
_SIMILARITY_THRESHOLD = 0.75


class _L1SearchStore(Protocol):
    def has_content_hash(self, digest: str) -> bool: ...

    def search(
        self,
        query: str,
        *,
        session_key: str | None = None,
        limit: int = 5,
    ) -> list[Any]: ...


def normalize_content(text: str) -> str:
    return _WS_RE.sub(" ", text.strip().lower())


def content_hash(text: str) -> str:
    normalized = normalize_content(text)
    return hashlib.sha256(normalized.encode()).hexdigest()


def text_similarity(a: str, b: str) -> float:
    ta = set(normalize_content(a).split())
    tb = set(normalize_content(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_duplicate(
    proposed: str,
    store: _L1SearchStore,
    *,
    session_key: str,
    enable_dedup: bool,
) -> bool:
    """Return True when ``proposed`` should be skipped (exact hash or near-duplicate)."""
    normalized = proposed.strip()
    if not normalized:
        return True
    digest = content_hash(normalized)
    if store.has_content_hash(digest):
        return True
    if not enable_dedup:
        return False
    hits = store.search(normalized, session_key=session_key, limit=3)
    for hit in hits:
        if text_similarity(hit.content, normalized) >= _SIMILARITY_THRESHOLD:
            return True
    return False
