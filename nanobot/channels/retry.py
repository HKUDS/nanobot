"""Channel retry helpers and health tracking.

Provides:

- ``ChannelHealth`` — per-channel delivery health dataclass.
- ``is_transient`` — classify whether an exception is worth retrying.
- ``retry_send`` — retry a send coroutine with exponential backoff + health tracking.
- ``connection_loop`` — generic reconnection loop with capped exponential backoff.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from loguru import logger


@dataclass(slots=True)
class ChannelHealth:
    """Tracks delivery health for a single channel."""

    healthy: bool = True
    consecutive_failures: int = 0
    last_error: str | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None

    def record_success(self) -> None:
        self.healthy = True
        self.consecutive_failures = 0
        self.last_success_at = time.monotonic()

    def record_failure(self, exc: Exception) -> None:
        self.healthy = False
        self.consecutive_failures += 1
        self.last_error = str(exc)
        self.last_failure_at = time.monotonic()


def is_transient(exc: Exception) -> bool:
    """Return True if *exc* looks like a transient network/server error."""
    transient_types = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
        OSError,
    )
    if isinstance(exc, transient_types):
        return True
    msg = str(exc).lower()
    return any(tok in msg for tok in ("429", "500", "502", "503", "504", "rate limit"))


async def retry_send(
    send_fn: Callable[[], Awaitable[None]],
    *,
    channel_name: str,
    health: ChannelHealth | None = None,
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> None:
    """Retry *send_fn* for transient errors with exponential backoff.

    Records success/failure on *health* when provided.  Non-transient
    errors and the final transient failure are re-raised immediately.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            await send_fn()
            if health:
                health.record_success()
            return
        # crash-barrier: retry logic must catch all transient errors
        except Exception as exc:
            if health:
                health.record_failure(exc)
            if attempt < max_attempts and is_transient(exc):
                delay = base_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.3)  # noqa: S311
                logger.warning(
                    "{} send attempt {}/{} failed ({}), retrying in {:.1f}s...",
                    channel_name,
                    attempt,
                    max_attempts,
                    exc,
                    delay + jitter,
                )
                await asyncio.sleep(delay + jitter)
                continue
            raise


async def connection_loop(
    name: str,
    connect_fn: Callable[[], Awaitable[None]],
    *,
    running_flag: Callable[[], bool],
    min_delay: float = 5.0,
    max_delay: float = 60.0,
) -> None:
    """Reconnection loop with capped exponential backoff + jitter.

    *connect_fn* should block while the connection is alive and return
    (or raise) when it drops.  The loop will reconnect automatically
    while *running_flag()* returns ``True``.
    """
    consecutive_failures = 0
    while running_flag():
        try:
            consecutive_failures = 0
            await connect_fn()
        except asyncio.CancelledError:
            break
        except Exception as e:  # crash-barrier: user connection callback
            consecutive_failures += 1
            logger.warning("{} connection error: {}", name, e)

        if running_flag():
            delay = min(min_delay * (2 ** min(consecutive_failures, 5)), max_delay)
            jitter = random.uniform(0, delay * 0.2)  # noqa: S311
            logger.info("Reconnecting {} in {:.1f}s...", name, delay + jitter)
            await asyncio.sleep(delay + jitter)
