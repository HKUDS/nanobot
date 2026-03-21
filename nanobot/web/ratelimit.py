"""Simple per-IP sliding-window rate limiting middleware for the web API.

Uses a token-bucket approach keyed by client IP.  Only ``/api/*`` paths are
rate-limited; health probes (``/health``, ``/ready``) are exempt.

No external dependencies — implemented on top of Starlette primitives.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by client IP.

    Args:
        app: The ASGI application to wrap.
        requests_per_minute: Maximum requests allowed per IP per 60-second window.
            A value of 0 disables rate limiting entirely.
        api_prefix: Only paths that start with this prefix are rate-limited.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int = 60,
        api_prefix: str = "/api",
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._api_prefix = api_prefix
        # ip → deque of request timestamps (monotonic seconds)
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def _get_client_ip(self, request: Request) -> str:
        """Extract the real client IP, respecting X-Forwarded-For when present."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only rate-limit API routes; skip health probes and static assets
        if self._limit <= 0 or not request.url.path.startswith(self._api_prefix):
            return await call_next(request)

        ip = self._get_client_ip(request)
        now = time.monotonic()
        window_start = now - 60.0

        bucket = self._windows[ip]
        # Evict timestamps older than the 60-second window
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self._limit:
            retry_after = int(60 - (now - bucket[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return await call_next(request)
