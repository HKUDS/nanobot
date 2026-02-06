"""Rate limiting utilities for API calls."""

import threading
import time
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class RateLimitEntry:
    """Track rate limit state for a user."""
    request_count: int = 0
    window_start: float = field(default_factory=time.time)
    blocked_until: float = 0.0
    last_accessed: float = field(default_factory=time.time)


class RateLimiter:
    """
    Token bucket rate limiter for per-user API quotas.

    Prevents abuse of expensive APIs (TTS, transcription) by limiting
    the number of requests per user within a time window.

    Memory Management:
    - Old entries are automatically expired after max_age_seconds
    - Total entries are limited to max_entries (LRU eviction)
    - Cleanup runs periodically to prevent memory exhaustion

    Thread-safety: Uses threading.Lock to protect _state dictionary access,
    preventing RuntimeError during dictionary iteration when cleanup runs.
    """

    # Cleanup runs every CLEANUP_INTERVAL calls to avoid overhead on every request
    CLEANUP_INTERVAL = 100

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        block_duration: int = 300,
        max_age_seconds: int = 3600,
        max_entries: int = 10000,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed per window per user.
            window_seconds: Time window in seconds.
            block_duration: How long to block a user who exceeds limits (seconds).
            max_age_seconds: Expire entries after this many seconds (default: 1 hour).
            max_entries: Maximum number of user entries to keep (default: 10000).
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.block_duration = block_duration
        self.max_age_seconds = max_age_seconds
        self.max_entries = max_entries
        # Use regular dict instead of defaultdict to avoid auto-creating entries
        # This prevents memory leaks from spurious user_ids and makes access explicit
        self._state: dict[str, RateLimitEntry] = {}
        self._access_count = 0  # Track accesses to trigger periodic cleanup
        self._lock = threading.Lock()  # Protect _state from concurrent access

    def is_allowed(self, user_id: str) -> tuple[bool, str | None]:
        """
        Check if a request from this user is allowed.

        Args:
            user_id: Unique identifier for the user.

        Returns:
            Tuple of (is_allowed, error_message).
        """
        now = time.time()

        with self._lock:
            # Periodic cleanup to prevent memory exhaustion
            self._access_count += 1
            if self._access_count >= self.CLEANUP_INTERVAL:
                self._cleanup(now)
                self._access_count = 0

            # Get or create entry explicitly (not using defaultdict)
            entry = self._state.get(user_id)
            if entry is None:
                entry = RateLimitEntry()
                self._state[user_id] = entry

            # Update last accessed time
            entry.last_accessed = now

            # Check if user is currently blocked
            if now < entry.blocked_until:
                remaining = int(entry.blocked_until - now)
                return False, f"Rate limit exceeded. Try again in {remaining}s."

            # Reset window if expired
            if now - entry.window_start >= self.window_seconds:
                entry.request_count = 0
                entry.window_start = now

            # Check if within limit
            if entry.request_count >= self.max_requests:
                # Block the user
                entry.blocked_until = now + self.block_duration
                logger.warning(
                    f"Rate limit exceeded for user {user_id}. "
                    f"Blocking for {self.block_duration}s."
                )
                return False, f"Rate limit exceeded ({self.max_requests} requests/{self.window_seconds}s)."

            # Allow the request
            entry.request_count += 1
            logger.debug(
                f"Rate limit: {user_id} at {entry.request_count}/{self.max_requests} "
                f"requests this window"
            )
            return True, None

    def _cleanup(self, now: float) -> None:
        """
        Clean up expired and excess entries to prevent memory exhaustion.

        Note: This method assumes self._lock is already held by the caller.
        It is only called from within is_allowed() which holds the lock.

        Args:
            now: Current timestamp from time.time().
        """
        if not self._state:
            return

        # Remove entries older than max_age_seconds
        if self.max_age_seconds > 0:
            expired_keys = [
                user_id for user_id, entry in self._state.items()
                if now - entry.last_accessed > self.max_age_seconds
            ]
            for key in expired_keys:
                del self._state[key]

            if expired_keys:
                logger.debug(
                    f"RateLimiter: Cleaned up {len(expired_keys)} expired entries "
                    f"(age > {self.max_age_seconds}s)"
                )

        # If still over max_entries, remove least recently accessed entries
        if self.max_entries > 0 and len(self._state) > self.max_entries:
            # Sort by last_accessed (oldest first) and remove excess
            sorted_entries = sorted(
                self._state.items(),
                key=lambda item: item[1].last_accessed
            )
            excess = len(self._state) - self.max_entries
            for user_id, _ in sorted_entries[:excess]:
                del self._state[user_id]

            logger.debug(
                f"RateLimiter: Removed {excess} excess entries "
                f"(total: {len(self._state)}/{self.max_entries})"
            )

    def reset(self, user_id: str | None = None) -> None:
        """
        Reset rate limit state.

        Thread-safe: Acquires lock before modifying state.

        Args:
            user_id: Specific user to reset, or None to reset all.
        """
        with self._lock:
            if user_id:
                if user_id in self._state:
                    del self._state[user_id]
            else:
                self._state.clear()


# Predefined rate limiter configurations for common use cases
# These reduce code duplication compared to creating separate classes


def tts_rate_limiter() -> RateLimiter:
    """
    Create a rate limiter for TTS requests.

    Default: 10 TTS requests per minute, block for 5 minutes on abuse.
    """
    return RateLimiter(
        max_requests=10,
        window_seconds=60,
        block_duration=300,
    )


def transcription_rate_limiter() -> RateLimiter:
    """
    Create a rate limiter for transcription requests.

    Default: 20 transcriptions per minute, block for 5 minutes on abuse.
    """
    return RateLimiter(
        max_requests=20,
        window_seconds=60,
        block_duration=300,
    )


def video_rate_limiter() -> RateLimiter:
    """
    Create a rate limiter for video processing operations.

    Default: 3 videos per 5 minutes, block for 10 minutes on abuse.
    """
    return RateLimiter(
        max_requests=3,
        window_seconds=300,
        block_duration=600,
    )


def vision_rate_limiter() -> RateLimiter:
    """
    Create a rate limiter for vision/image processing.

    Default: 20 images per minute, block for 5 minutes on abuse.
    """
    return RateLimiter(
        max_requests=20,
        window_seconds=60,
        block_duration=300,
    )
