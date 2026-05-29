"""Per-turn budget for memory_search + conversation_search (LM2-E)."""

from __future__ import annotations

import contextvars

_calls: contextvars.ContextVar[int] = contextvars.ContextVar("layered_memory_search_calls", default=0)


def reset_memory_search_calls() -> None:
    _calls.set(0)


def memory_search_calls_used() -> int:
    return _calls.get()


def try_consume_memory_search_call(*, limit: int) -> bool:
    """Increment combined search counter; return False when over *limit*."""
    if limit <= 0:
        return False
    next_count = _calls.get() + 1
    if next_count > limit:
        return False
    _calls.set(next_count)
    return True
