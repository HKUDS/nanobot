"""FastAPI application factory for the nanobot web interface.

This module's sole responsibility is assembling the FastAPI app:
  - creating the FastAPI instance and reading the version
  - attaching CORS middleware
  - storing shared services on app.state
  - including all routes from nanobot.web.routes

Route logic lives in routes.py; utility functions live in utils.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nanobot.web.routes import register_routes

if TYPE_CHECKING:
    from nanobot.channels.web import WebChannel
    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager


def _get_version() -> str:
    """Return the nanobot package version as the API version string."""
    from nanobot import __version__
    return __version__


def create_app(
    *,
    web_channel: WebChannel,
    session_manager: SessionManager | None,
    config: Config | None,
    cron_service: CronService | None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        web_channel:     The WebChannel instance that manages WebSocket connections.
        session_manager: Shared SessionManager from the gateway.
        config:          Full nanobot Config loaded by the gateway.
        cron_service:    Shared CronService from the gateway.

    Returns:
        A fully configured FastAPI application ready to be served by uvicorn.
    """
    app = FastAPI(
        title="nanobot-web",
        version=_get_version(),
        description="nanobot HTTP + WebSocket API for the browser frontend",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store services on app.state so routes can access them via Depends()
    app.state.web_channel = web_channel
    app.state.session_manager = session_manager
    app.state.config = config
    app.state.cron_service = cron_service

    register_routes(app)
    return app
