"""FastAPI application factory for the nanobot dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nanobot.web import api
from nanobot.web.events import DashboardEventBus
from nanobot.web.ws import websocket_endpoint

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

# Static files directory (built React SPA)
_STATIC_DIR = Path(__file__).parent / "static"


def create_dashboard(
    agent_loop: "AgentLoop",
    channel_manager: "ChannelManager",
    bus: "MessageBus",
    config: "Config",
) -> FastAPI:
    """Create and configure the dashboard FastAPI application."""

    app = FastAPI(title="nanobot dashboard", docs_url="/api/docs", redoc_url=None)

    # CORS for dev (Vite dev server on :5173)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure API routes
    api.configure(agent_loop, channel_manager, bus, config)
    app.include_router(api.router)

    # Dashboard event bus
    event_bus = DashboardEventBus()

    # Subscribe to message bus
    bus.add_inbound_observer(event_bus.on_inbound)
    bus.add_outbound_observer(event_bus.on_outbound)
    bus.add_dashboard_observer(event_bus.on_dashboard_event)

    # WebSocket endpoint
    @app.websocket("/api/ws")
    async def ws_route(ws: WebSocket):
        await websocket_endpoint(ws, event_bus)

    # Serve React SPA static files
    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app
