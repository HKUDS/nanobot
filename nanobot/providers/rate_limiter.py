"""Rolling-window rate limiter for LLM API calls.

Tracks prompt tokens sent within a 60-second window and introduces
async delays when approaching the provider's rate limit.  Currently
used for Anthropic's 50k input tokens/minute limit.

Designed for deletion: if the rate limit is increased or becomes
irrelevant, remove this file and the optional ``rate_limiter``
parameter from ``StreamingLLMCaller``.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from loguru import logger


@dataclass(slots=True)
class TokenRecord:
    """A single token-usage entry in the rolling window."""

    timestamp: float
    tokens: int


_WINDOW_SECONDS: float = 60.0


class RateLimiter:
    """Rolling-window token rate limiter.

    Tracks prompt tokens sent within the last 60 seconds.  When the
    total approaches ``threshold`` fraction of ``tokens_per_minute``,
    ``wait_if_needed()`` sleeps until enough old entries expire.

    Args:
        tokens_per_minute: The provider's rate limit.
        threshold: Fraction (0-1) at which to start sleeping.
    """

    def __init__(self, tokens_per_minute: int, threshold: float = 0.80) -> None:
        self._limit = tokens_per_minute
        self._threshold = threshold
        self._window: deque[TokenRecord] = deque()

    def _prune(self, now: float) -> None:
        """Remove entries older than 60 seconds."""
        cutoff = now - _WINDOW_SECONDS
        while self._window and self._window[0].timestamp < cutoff:
            self._window.popleft()

    def window_total(self) -> int:
        """Current token count in the rolling window."""
        self._prune(time.monotonic())
        return sum(r.tokens for r in self._window)

    async def wait_if_needed(self) -> float:
        """Sleep if approaching rate limit.  Returns seconds waited."""
        now = time.monotonic()
        self._prune(now)
        total = sum(r.tokens for r in self._window)
        if total < self._limit * self._threshold:
            return 0.0

        # Wait until the oldest entry expires from the window
        sleep_time = self._window[0].timestamp + _WINDOW_SECONDS - now + 0.5
        sleep_time = max(1.0, min(sleep_time, 15.0))
        logger.info(
            "Rate limiter: {}k/{}k tokens in window, sleeping {:.1f}s",
            total // 1000,
            self._limit // 1000,
            sleep_time,
        )
        await asyncio.sleep(sleep_time)
        return sleep_time

    def record(self, tokens: int) -> None:
        """Record tokens sent in the current call."""
        if tokens > 0:
            self._window.append(TokenRecord(time.monotonic(), tokens))
