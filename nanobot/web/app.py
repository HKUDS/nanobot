"""FastAPI application factory for the nanobot web UI."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from nanobot.web.ratelimit import RateLimitMiddleware
from nanobot.web.routes import router

if TYPE_CHECKING:
    from nanobot.channels.web import WebChannel


class _ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <api_key> for all /api/* routes (SEC-06)."""

    def __init__(self, app: Any, api_key: str) -> None:
        super().__init__(app)
        self._api_key_bytes = api_key.encode()

    async def dispatch(  # type: ignore[override]
        self, request: StarletteRequest, call_next: Any
    ) -> Any:
        if request.url.path.startswith("/api/"):
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip().encode()
            # Constant-time comparison prevents timing-based key enumeration
            if not hmac.compare_digest(token, self._api_key_bytes):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def create_app(
    agent_loop: Any,
    session_manager: Any,
    web_channel: WebChannel,
    *,
    static_dir: Path | None = None,
    uploads_dir: Path | None = None,
    owns_lifecycle: bool = False,
    api_key: str = "",
    rate_limit_per_minute: int = 60,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        session_manager: An initialized SessionManager instance.
        web_channel: The WebChannel bridging HTTP to the message bus.
        static_dir: Optional path to built frontend static files to serve.
        uploads_dir: Directory for saving uploaded file attachments.
        owns_lifecycle: If True, the app lifespan shuts down the agent on exit.
            Set to False when the gateway manages shutdown externally.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[misc]
        yield
        if owns_lifecycle:
            try:
                agent_loop.stop()
                await agent_loop.close_mcp()
            except Exception:  # noqa: BLE001  # crash-barrier: shutdown cleanup
                pass

    app = FastAPI(
        title="Nanobot Web UI",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store references accessible from routes via request.app.state
    app.state.agent_loop = agent_loop
    app.state.session_manager = session_manager
    app.state.web_channel = web_channel

    # Uploads directory for file attachments
    _uploads = uploads_dir or Path.home() / ".nanobot" / "workspace" / "uploads"
    _uploads.mkdir(parents=True, exist_ok=True)
    app.state.uploads_dir = _uploads

    # Rate limiting — applied to /api/* routes only; health probes are exempt
    if rate_limit_per_minute > 0:
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=rate_limit_per_minute,
        )

    # CORS for local development (React dev server on :5173)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Thread-Id"],
    )

    # API key authentication middleware (SEC-06) — only active when api_key is set
    if api_key:
        app.add_middleware(_ApiKeyMiddleware, api_key=api_key)

    # Health check routes (outside /api — used by Docker HEALTHCHECK & probes)
    @app.get("/health", tags=["health"])
    async def health() -> dict:
        """Liveness probe — returns 200 if the process is alive."""
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready():  # type: ignore[return]
        """Readiness probe — returns 200 if the agent loop is accepting work."""
        loop = app.state.agent_loop
        if loop and getattr(loop, "_running", False):
            return {"status": "ready"}
        return JSONResponse({"status": "not_ready"}, status_code=503)

    # API routes
    app.include_router(router)

    # Optional Prometheus /metrics endpoint — only active when prometheus_client is installed.
    try:
        from prometheus_client import make_asgi_app

        metrics_app = make_asgi_app()
        app.mount("/metrics", metrics_app)
    except ImportError:
        pass

    # Serve built frontend if available
    if static_dir and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
