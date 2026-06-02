"""Shared L1 FTS search for recall and memory_search tool."""

from __future__ import annotations

from loguru import logger

from nanobot.agent.layered_memory.l1_store import L1Memory, L1Store


def search_l1_memories(
    store: L1Store,
    query: str,
    session_key: str,
    *,
    limit: int,
    strategy: str = "fts",
) -> list[L1Memory]:
    """Search L1 atoms; workspace-wide first, then same-session fallback."""
    text = query.strip()
    if not text:
        return []
    if strategy in {"embedding", "hybrid"}:
        logger.debug(
            "layered_memory l1_search strategy={} using fts fallback session={}",
            strategy,
            session_key,
        )
    hits = store.search(text, session_key=None, limit=limit)
    if hits:
        return hits
    return store.search(text, session_key=session_key, limit=limit)
