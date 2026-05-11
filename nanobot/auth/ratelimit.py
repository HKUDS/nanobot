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

    _SWEEP_EVERY = 256  # number of try_consume calls between sweeps
    _MAX_BUCKETS = 50_000  # hard cap; sweep on hit to bound memory

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._now = now or time.monotonic
        self._calls_since_sweep = 0

    def try_consume(self, key: tuple[str, str], *, max_attempts: int, window_s: float) -> tuple[bool, int]:
        self._calls_since_sweep += 1
        if (
            self._calls_since_sweep >= self._SWEEP_EVERY
            or len(self._buckets) >= self._MAX_BUCKETS
        ):
            self.sweep(window_s=window_s)
            self._calls_since_sweep = 0
        now = self._now()
        bucket = self._buckets.setdefault(key, _Bucket())
        cutoff = now - window_s
        while bucket.hits and bucket.hits[0] < cutoff:
            bucket.hits.popleft()
        if len(bucket.hits) >= max_attempts:
            retry_after = max(1, int(bucket.hits[0] + window_s - now) + 1)
            return False, retry_after
        bucket.hits.append(now)
        # Drop empty buckets so an IPv6-rotating attacker can't grow this
        # dict without bound. The append above guarantees we never reap a
        # bucket we just touched.
        if not bucket.hits:  # pragma: no cover — defensive, append makes this unreachable
            self._buckets.pop(key, None)
        return True, 0

    def sweep(self, *, window_s: float) -> int:
        """Remove buckets whose newest hit is older than ``window_s``.

        Safe to call opportunistically. Returns the number of buckets removed.
        """
        now = self._now()
        cutoff = now - window_s
        dead = [k for k, b in self._buckets.items() if not b.hits or b.hits[-1] < cutoff]
        for k in dead:
            self._buckets.pop(k, None)
        return len(dead)

    def reset(self) -> None:
        self._buckets.clear()
