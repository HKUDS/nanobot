"""In-memory token bucket for /auth/* endpoints.

Simple sliding-window counter keyed by (path, ip). Suitable for a
single-instance gateway. Replace with a Redis-backed limiter when we
horizontally scale.

Thread-safety: callers are async-single-threaded (asyncio event loop).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _Bucket:
    hits: deque[float] = field(default_factory=deque)


class RateLimiter:
    """Per-(path, ip) sliding-window limiter.

    ``try_consume`` returns ``(allowed, retry_after_s)``. When ``allowed``
    is False the response should include ``Retry-After: retry_after_s``.
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._now = now or time.monotonic

    def try_consume(self, key: tuple[str, str], *, max_attempts: int, window_s: float) -> tuple[bool, int]:
        now = self._now()
        bucket = self._buckets.setdefault(key, _Bucket())
        cutoff = now - window_s
        while bucket.hits and bucket.hits[0] < cutoff:
            bucket.hits.popleft()
        if len(bucket.hits) >= max_attempts:
            retry_after = max(1, int(bucket.hits[0] + window_s - now) + 1)
            return False, retry_after
        bucket.hits.append(now)
        return True, 0

    def reset(self) -> None:
        self._buckets.clear()
