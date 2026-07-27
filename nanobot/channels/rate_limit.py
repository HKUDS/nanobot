"""Lightweight in-process per-sender message rate limiting for channels.

Private-assistant scale: no external store, just a small sliding-window
counter kept in memory per ``(channel, sender)`` pair. This is intentionally
simple — it resets on process restart and is not shared across multiple
gateway processes, which matches how pairing/session state already works
for nanobot's single-process deployment model.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string identity.

    ``per_minute`` caps the number of messages allowed in any trailing
    60-second window. ``burst`` optionally caps a shorter trailing window
    (``burst_window_s`` seconds, default 10s) to catch rapid-fire bursts
    that would otherwise be smoothed out by the per-minute window alone.

    A ``per_minute`` of 0 (the default) disables rate limiting entirely.
    """

    per_minute: int = 0
    burst: int | None = None
    burst_window_s: float = 10.0
    _hits: dict[str, deque[float]] = field(default_factory=dict, repr=False)

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def check(self, key: str, *, now: float | None = None) -> float | None:
        """Record a message attempt for *key* and return a cooldown in seconds.

        Returns ``None`` when the message is allowed. Returns the number of
        seconds until the next message would be allowed when *key* has
        exceeded either the per-minute or burst limit. The attempt is still
        recorded even when it will not need retrying (matches token-bucket
        style limiters where rejected calls still count toward history for
        the purposes of computing the next allowed time).
        """
        if not self.enabled:
            return None

        current = time.monotonic() if now is None else now
        window = self._hits.setdefault(key, deque())

        # Drop timestamps outside the 60s window (deque is time-ordered).
        cutoff = current - 60.0
        while window and window[0] <= cutoff:
            window.popleft()

        retry_after = None
        if len(window) >= self.per_minute:
            retry_after = window[0] + 60.0 - current

        if self.burst and self.burst > 0:
            burst_cutoff = current - self.burst_window_s
            burst_count = sum(1 for ts in window if ts > burst_cutoff)
            if burst_count >= self.burst:
                burst_retry = window[-burst_count] + self.burst_window_s - current
                retry_after = burst_retry if retry_after is None else max(retry_after, burst_retry)

        if retry_after is not None:
            return max(retry_after, 0.0)

        window.append(current)
        return None

    def reset(self, key: str | None = None) -> None:
        """Clear rate-limit history for *key*, or every key when omitted."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


def format_cooldown_reply(retry_after: float) -> str:
    """Return a short, friendly message for a rate-limited sender."""
    seconds = max(1, round(retry_after))
    unit = "second" if seconds == 1 else "seconds"
    return f"You're sending messages too quickly. Please wait {seconds} {unit} and try again."
