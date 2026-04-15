"""WebSocket + REST server for Kosmos project/task management."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

import aiosqlite
from aiohttp import web
from websockets.server import WebSocketServerProtocol, serve

from nanobot.kosmos import api as kosmos_api
from nanobot.kosmos import database
from nanobot.kosmos.api import EventBroadcaster

logger = logging.getLogger("nanobot.kosmos")

DEFAULT_PORT = 18794
DATABASE_PATH = Path.home() / ".nanobot" / "kosmos.db"


class KosmosServer(EventBroadcaster):
    """Combined REST + WebSocket server for Kosmos."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        db_path: Path = DATABASE_PATH,
    ):
        self.host = host
        self.port = port
        self.db_path = db_path

        self.clients: Set[WebSocketServerProtocol] = set()
        self.agents: Dict[str, Any] = {}
        self.db: Optional[aiosqlite.Connection] = None

        # Database operations
        self.db_ops = database

    # ------------------------------------------------------------------------
    # Database lifecycle
    # ------------------------------------------------------------------------

    async def init_db(self) -> aiosqlite.Connection:
        """Initialize database connection."""
        self.db = await database.init_db(self.db_path)
        return self.db

    async def close_db(self):
        """Close database connection."""
        if self.db:
            await self.db.close()
            self.db = None

    # ------------------------------------------------------------------------
    # Event broadcasting (WebSocket)
    # ------------------------------------------------------------------------

    async def broadcast_event(self, event_type: str, payload: Any):
        """Broadcast an event to all connected WebSocket clients."""
        if not self.clients:
            return

        message = json.dumps(
            {
                "type": event_type,
                "payload": payload,
            }
        )

        dead_clients = set()
        for client in self.clients:
            try:
                await client.send(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                dead_clients.add(client)

        self.clients.difference_update(dead_clients)
        logger.debug(
            "Broadcast {} to {} clients", event_type, len(self.clients) - len(dead_clients)
        )

    # ------------------------------------------------------------------------
    # Agent state management (from nanobot WebSocket events)
    # ------------------------------------------------------------------------

    async def handle_agent_event(self, event_data: Dict[str, Any]):
        """Handle agent update events from nanobot."""
        agent_id = event_data.get("id")
        if agent_id:
            self.agents[agent_id] = event_data
            await self.broadcast_event("agent_update", event_data)

    async def handle_activity_event(self, event_data: Dict[str, Any]):
        """Handle activity events from nanobot."""
        await self.broadcast_event("activity", event_data)

    # ------------------------------------------------------------------------
    # WebSocket handler
    # ------------------------------------------------------------------------

    async def websocket_handler(self, ws: WebSocketServerProtocol, path: str):
        """Handle WebSocket connection."""
        self.clients.add(ws)
        logger.info("Kosmos client connected from {}", ws.remote_address[0])

        # Send initial state
        try:
            # Send agents
            await ws.send(
                json.dumps(
                    {
                        "type": "agent_update",
                        "payload": list(self.agents.values()),
                    }
                )
            )

            # Send current projects with task count
            if self.db:
                projects = await self.db_ops.get_projects_with_task_count(
                    self.db, include_hidden=True
                )
                await ws.send(
                    json.dumps(
                        {
                            "type": "project_status",
                            "payload": projects,
                        }
                    )
                )

                # Send tasks
                tasks = await self.db_ops.get_tasks(self.db)
                await ws.send(
                    json.dumps(
                        {
                            "type": "task_status",
                            "payload": tasks,
                        }
                    )
                )

        except Exception as e:
            logger.warning("Failed to send initial state: {}", e)

        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))

                    elif msg_type == "agent_update":
                        await self.handle_agent_event(data.get("payload", {}))

                    elif msg_type == "activity":
                        await self.handle_activity_event(data.get("payload", {}))

                    # Forward nanobot events
                    elif msg_type in ("nanobot:agent_update", "nanobot:activity"):
                        payload = data.get("payload", {})
                        await self.broadcast_event(msg_type, payload)

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from client")

        except Exception as e:
            logger.warning("WebSocket error: {}", e)
        finally:
            self.clients.discard(ws)
            logger.info("Kosmos client disconnected")

    # ------------------------------------------------------------------------
    # REST app factory
    # ------------------------------------------------------------------------

    def create_app(self) -> web.Application:
        """Create the aiohttp REST application."""

        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
            }
            if request.method == "OPTIONS":
                return web.Response(status=204, headers=headers)

            response = await handler(request)
            for key, value in headers.items():
                response.headers[key] = value
            return response

        app = web.Application(middlewares=[cors_middleware])

        # Store references
        app["kosmos_db"] = self.db
        app["db_ops"] = self.db_ops
        app["broadcaster"] = self
        app["agents"] = self.agents

        # Add REST routes
        kosmos_api.add_routes(app)

        # Store self reference for later db assignment
        app["kosmos_server"] = self

        return app

    # ------------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------------

    async def start(self):
        """Start the combined REST + WebSocket server."""
        # Initialize database
        await self.init_db()

        # Create REST app
        app = self.create_app()

        # Update app with db reference after init
        app["kosmos_db"] = self.db

        # Create WebSocket runner

        async def run_websocket():
            async with serve(self.websocket_handler, self.host, self.port + 1):
                await asyncio.Future()

        # Create REST runner
        rest_runner = web.AppRunner(app)
        await rest_runner.setup()
        rest_site = web.TCPSite(rest_runner, self.host, self.port)

        logger.info("Starting Kosmos REST server on http://{}:{}", self.host, self.port)
        logger.info("Starting Kosmos WebSocket server on ws://{}:{}", self.host, self.port + 1)

        # Start both servers
        await rest_site.start()

        try:
            await run_websocket()
        finally:
            await rest_runner.cleanup()
            await self.close_db()

    def run(self):
        """Run the server (blocking)."""
        asyncio.run(self.start())


def parse_kosmos_base_url(base_url: str) -> tuple[str, int]:
    """Parse a Kosmos API base URL into host/port."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_PORT
    return host, port
