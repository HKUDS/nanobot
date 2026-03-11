"""Web channel with WebSocket support for real-time browser communication."""

from __future__ import annotations

import asyncio
import json
from typing import Any, TYPE_CHECKING

from loguru import logger
from starlette.websockets import WebSocket, WebSocketDisconnect

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebConfig

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager
    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService


class WebChannel(BaseChannel):
    """
    Web channel that serves a FastAPI app with WebSocket endpoints.

    Messages flow through the MessageBus like all other channels:
    - Browser sends via WebSocket -> _handle_message() -> bus.inbound
    - AgentLoop processes -> bus.outbound -> send() -> WebSocket push
    - If browser is disconnected, send() is a no-op (session is already persisted).
    """

    name = "web"

    def __init__(
        self,
        config: WebConfig,
        bus: MessageBus,
        session_manager: "SessionManager | None" = None,
        full_config: "Config | None" = None,
        cron_service: "CronService | None" = None,
    ):
        super().__init__(config, bus)
        self.session_manager = session_manager
        self.full_config = full_config
        self.cron_service = cron_service
        # session_id -> set of connected WebSocket instances
        self._connections: dict[str, set[WebSocket]] = {}
        self._server: Any = None  # uvicorn.Server, set in start()

    async def start(self) -> None:
        """Start the FastAPI/uvicorn server as an async task."""
        self._running = True
        logger.info(f"Web channel starting on {self.config.host}:{self.config.port}")

        try:
            import uvicorn
        except ImportError:
            logger.error("uvicorn not installed. Run: pip install uvicorn[standard]")
            self._running = False
            return

        from nanobot.web.server import create_app

        app = create_app(
            bus=self.bus,
            web_channel=self,
            session_manager=self.session_manager,
            config=self.full_config,
            cron_service=self.cron_service,
        )

        uvi_config = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(uvi_config)
        await self._server.serve()

    async def stop(self) -> None:
        """Close all WebSocket connections and stop the server."""
        self._running = False
        # Signal uvicorn to exit
        if self._server is not None:
            self._server.should_exit = True
        # Close every connected WebSocket
        for session_id, sockets in list(self._connections.items()):
            for ws in list(sockets):
                try:
                    await ws.close()
                except Exception:
                    pass
            sockets.clear()
        self._connections.clear()
        logger.info("Web channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Push an outbound message to all connected WebSocket clients for this chat_id."""
        payload_dict: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "content": msg.content,
        }
        attachments = msg.metadata.get("attachments")
        if attachments:
            payload_dict["attachments"] = attachments
        payload = json.dumps(payload_dict)
        await self._broadcast(msg.chat_id, payload)

    # ------------------------------------------------------------------
    # Connection management (called by the WebSocket endpoint in server.py)
    # ------------------------------------------------------------------

    def register_connection(self, session_id: str, ws: WebSocket) -> None:
        """Register a WebSocket connection for a session."""
        if session_id not in self._connections:
            self._connections[session_id] = set()
        self._connections[session_id].add(ws)
        logger.debug(f"WebSocket registered for session {session_id} "
                      f"(total: {len(self._connections[session_id])})")

    def unregister_connection(self, session_id: str, ws: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        sockets = self._connections.get(session_id)
        if sockets:
            sockets.discard(ws)
            if not sockets:
                del self._connections[session_id]
        logger.debug(f"WebSocket unregistered for session {session_id}")

    async def notify_thinking(self, session_id: str) -> None:
        """Broadcast a 'thinking' status to connected clients."""
        payload = json.dumps({"type": "status", "status": "thinking"})
        await self._broadcast(session_id, payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _broadcast(self, session_id: str, payload: str) -> None:
        """Send a text payload to all WebSockets for a given session_id."""
        sockets = self._connections.get(session_id)
        if not sockets:
            return
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            sockets.discard(ws)
        # Re-check dict to avoid race with unregister_connection
        if session_id in self._connections and not self._connections[session_id]:
            del self._connections[session_id]
