"""Web channel: browser ↔ nanobot via HTTP/WebSocket.

This channel integrates the FastAPI web server as a first-class nanobot channel,
equivalent in lifecycle to DingTalk, Feishu, and Telegram channels.

Lifecycle:
    start()  → launches uvicorn (long-running coroutine, same pattern as other channels)
    stop()   → signals uvicorn to exit gracefully
    send()   → broadcasts OutboundMessage to all WebSocket clients for the given chat_id

Inbound messages from browsers go through BaseChannel._handle_message(), which
enforces the allowFrom permission list before publishing to the message bus.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class WebChannelConfig(Base):
    """Configuration for the Web channel.

    All fields accept both camelCase (JSON config) and snake_case (Python).
    """

    enabled: bool = False
    port: int = 18790
    host: str = "0.0.0.0"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class WebChannel(BaseChannel):
    """Browser ↔ nanobot via FastAPI + WebSocket.

    The channel is discovered automatically by the channel registry (pkgutil scan)
    when web.py lives in nanobot/channels/.  No changes are needed in registry.py
    or manager.py.

    Services (session_manager, cron_service, config) are injected by the gateway
    after ChannelManager instantiates this channel, via set_services().
    """

    name = "web"
    display_name = "Web"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        # ChannelsConfig stores unknown channel sections as dicts (extra="allow").
        # Normalise to WebChannelConfig so attribute access is type-safe.
        if isinstance(config, dict):
            config = WebChannelConfig(**config)
        super().__init__(config, bus)

        # WebSocket connections: session_id → set of connected WebSocket instances
        self._connections: dict[str, set[WebSocket]] = {}

        # uvicorn.Server instance, set in start()
        self._server: Any = None

        # Services injected by the gateway after construction (see set_services)
        self._session_manager: SessionManager | None = None
        self._cron_service: CronService | None = None
        self._app_config: Config | None = None

    # ------------------------------------------------------------------
    # Service injection — called by gateway after ChannelManager creates us
    # ------------------------------------------------------------------

    def set_services(
        self,
        session_manager: SessionManager | None = None,
        cron_service: CronService | None = None,
        config: Config | None = None,
    ) -> None:
        """Inject shared gateway services needed by the FastAPI app factory.

        The gateway calls this immediately after creating ChannelManager,
        before start_all() is called.
        """
        self._session_manager = session_manager
        self._cron_service = cron_service
        self._app_config = config

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch uvicorn with the FastAPI app.

        Blocks until the server exits (same long-running pattern as DingTalk
        stream and Feishu WebSocket channels).

        Raises ImportError with a clear message when fastapi/uvicorn are not
        installed (the web optional-dependency group must be installed).
        """
        try:
            import uvicorn
            from nanobot.web.app import create_app
        except ImportError as exc:
            raise ImportError(
                "Web channel requires the 'web' extras: pip install 'nanobot-ai[web]'"
            ) from exc

        self._running = True

        app = create_app(
            web_channel=self,
            session_manager=self._session_manager,
            config=self._app_config,
            cron_service=self._cron_service,
        )

        host: str = getattr(self.config, "host", "0.0.0.0")
        port: int = getattr(self.config, "port", 18790)

        uvi_config = uvicorn.Config(app, host=host, port=port, log_level="info")
        self._server = uvicorn.Server(uvi_config)

        logger.info("Web channel starting on {}:{}", host, port)
        await self._server.serve()

    async def stop(self) -> None:
        """Signal uvicorn to exit gracefully."""
        self._running = False
        if self._server is not None:
            self._server.should_exit = True

    async def send(self, msg: OutboundMessage) -> None:
        """Push an outbound message to all WebSocket clients for msg.chat_id.

        Progress messages (metadata._progress=True) are sent as type "progress".
        Regular assistant replies are sent as type "message".
        """
        if msg.metadata.get("_progress"):
            payload = json.dumps(
                {
                    "type": "progress",
                    "content": msg.content or "",
                }
            )
        else:
            payload = json.dumps(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": msg.content,
                }
            )
        await self._broadcast(msg.chat_id, payload)

    # ------------------------------------------------------------------
    # WebSocket connection management (called from FastAPI routes)
    # ------------------------------------------------------------------

    def register(self, session_id: str, ws: WebSocket) -> None:
        """Register a new WebSocket connection for session_id."""
        self._connections.setdefault(session_id, set()).add(ws)
        logger.debug(
            "WS registered: session={} total={}",
            session_id,
            len(self._connections[session_id]),
        )

    def unregister(self, session_id: str, ws: WebSocket) -> None:
        """Remove a WebSocket connection; cleans up empty session entries."""
        sockets = self._connections.get(session_id)
        if sockets:
            sockets.discard(ws)
            if not sockets:
                del self._connections[session_id]
        logger.debug("WS unregistered: session={}", session_id)

    async def handle_ws_message(self, session_id: str, content: str) -> None:
        """Publish a browser message into the nanobot message bus (inbound path)."""
        await self._handle_message(
            sender_id="web_user",
            chat_id=session_id,
            content=content,
        )

    async def notify_thinking(self, session_id: str) -> None:
        """Send a 'thinking' status event to all clients for session_id."""
        payload = json.dumps({"type": "status", "status": "thinking"})
        await self._broadcast(session_id, payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _broadcast(self, session_id: str, payload: str) -> None:
        """Send payload to every connected WebSocket for session_id.

        Dead connections are silently removed.
        """
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

        if session_id in self._connections and not self._connections[session_id]:
            del self._connections[session_id]

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "port": 18790, "host": "0.0.0.0", "allowFrom": ["*"]}
