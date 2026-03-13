"""FastAPI application factory for the nanobot web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nanobot.web.routes import router


def create_app(
    agent_loop: Any,
    session_manager: Any,
    *,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        session_manager: An initialized SessionManager instance.
        static_dir: Optional path to built frontend static files to serve.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Shutdown: clean up agent resources
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
    )

    # API routes
    app.include_router(router)

    # Serve built frontend if available
    if static_dir and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
