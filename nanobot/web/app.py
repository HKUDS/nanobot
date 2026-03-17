"""FastAPI application factory for the nanobot web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from nanobot.web.routes import router

if TYPE_CHECKING:
    from nanobot.channels.web import WebChannel


def create_app(
    agent_loop: Any,
    session_manager: Any,
    web_channel: WebChannel,
    *,
    static_dir: Path | None = None,
    uploads_dir: Path | None = None,
    owns_lifecycle: bool = False,
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
    async def lifespan(app: FastAPI):
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

    # Health check routes (outside /api — used by Docker HEALTHCHECK & probes)
    @app.get("/health", tags=["health"])
    async def health():
        """Liveness probe — returns 200 if the process is alive."""
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready():
        """Readiness probe — returns 200 if the agent loop is accepting work."""
        loop = app.state.agent_loop
        if loop and getattr(loop, "_running", False):
            return {"status": "ready"}
        return JSONResponse({"status": "not_ready"}, status_code=503)

    # API routes
    app.include_router(router)

    # Serve built frontend if available
    if static_dir and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
