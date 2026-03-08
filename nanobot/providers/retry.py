"""Exponential backoff retry for LLM API rate limits.

Provides a generic async retry wrapper that detects HTTP 429 / rate-limit
errors from any provider and retries with exponential backoff.

No new dependencies — uses only the Python stdlib and logging via loguru.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

from loguru import logger

T = TypeVar("T")

# Default retry parameters
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_DELAY = 1.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_MAX_DELAY = 60.0  # cap per-retry delay


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect whether an exception represents an HTTP 429 / rate-limit error.

    Works across providers (LiteLLM, OpenAI SDK, httpx, generic HTTP errors)
    without importing provider-specific exception classes at module level.
    """
    # Check for status_code attribute (httpx.HTTPStatusError, litellm exceptions,
    # openai exceptions all expose this).
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True

    # Some wrappers nest the real status in .status or .http_status
    for attr in ("status", "http_status"):
        code = getattr(exc, attr, None)
        if code == 429:
            return True

    # Fallback: inspect the string representation for common rate-limit signals.
    err_str = str(exc).lower()
    rate_limit_keywords = ("rate limit", "rate_limit", "ratelimit", "429", "too many requests", "quota exceeded")
    return any(kw in err_str for kw in rate_limit_keywords)


def _extract_retry_after(exc: Exception) -> float | None:
    """Try to extract a Retry-After value (in seconds) from the exception.

    Many HTTP libraries attach the response or headers to the exception object.
    """
    # httpx / openai / litellm often attach a .response attribute
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after is not None:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass

    # Some wrappers store headers directly
    headers = getattr(exc, "headers", None) or {}
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after is not None:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass

    return None


async def with_retry(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay: float = DEFAULT_MAX_DELAY,
    **kwargs: Any,
) -> T:
    """Call *fn* with exponential backoff retry on rate-limit errors.

    Args:
        fn: The async callable to invoke.
        *args: Positional arguments forwarded to *fn*.
        max_retries: Maximum number of retry attempts (default 5).
        initial_delay: Initial wait in seconds before first retry (default 1).
        backoff_factor: Multiplier applied each retry (default 2 → 1s, 2s, 4s, 8s, 16s).
        max_delay: Cap on per-retry delay in seconds (default 60).
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The result of *fn* on success.

    Raises:
        The original exception if all retries are exhausted or if the error
        is not a rate-limit error.
    """
    delay = initial_delay

    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise

            if attempt >= max_retries:
                logger.error(
                    "Rate limit: all {} retries exhausted. Raising original error.",
                    max_retries,
                )
                raise

            # Prefer Retry-After header if available
            retry_after = _extract_retry_after(exc)
            wait = min(retry_after if retry_after is not None else delay, max_delay)

            logger.warning(
                "Rate limit hit (attempt {}/{}). Retrying in {:.1f}s{}...",
                attempt + 1,
                max_retries,
                wait,
                f" (Retry-After: {retry_after:.0f}s)" if retry_after is not None else "",
            )

            await asyncio.sleep(wait)
            delay = min(delay * backoff_factor, max_delay)

    # Should not be reached, but satisfies type checker
    raise RuntimeError("with_retry: unreachable")  # pragma: no cover
