"""HTTP channel — synchronous request-response mode."""

import asyncio
import uuid

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import HttpConfig


class HttpChannel(BaseChannel):
    """
    HTTP channel for synchronous request-response communication.

    External devices (e.g. M5Stack) POST a message and block until the agent
    replies. Each HTTP round-trip completes one conversation turn.
    """

    name = "http"

    def __init__(self, config: HttpConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: HttpConfig = config
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._app = web.Application()
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_get("/api/health", self._handle_health)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server."""
        self._running = True
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        logger.info(f"HTTP channel listening on {self.config.host}:{self.config.port}")
        # Keep running until stopped
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Shut down the HTTP server."""
        self._running = False
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        # Cancel any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def send(self, msg: OutboundMessage) -> None:
        """Resolve the pending future for the matching request."""
        request_id = (msg.metadata or {}).get("http_request_id")
        if not request_id:
            logger.warning("HTTP channel received outbound message without http_request_id")
            return
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(msg.content or "")
        else:
            logger.warning(f"HTTP channel: no pending future for request_id={request_id}")

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """Handle POST /api/chat."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        message = body.get("message", "").strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)

        session_id = body.get("session_id") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # Access control
        sender_id = session_id
        if not self.is_allowed(sender_id):
            return web.json_response({"error": "access denied"}, status=403)

        # Create a future and register it
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[request_id] = fut

        # Publish inbound message with request_id in metadata
        await self._handle_message(
            sender_id=sender_id,
            chat_id=session_id,
            content=message,
            metadata={"http_request_id": request_id},
        )

        # Wait for the agent to reply
        try:
            reply = await asyncio.wait_for(fut, timeout=120)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return web.json_response({"error": "timeout"}, status=504)

        return web.json_response({"reply": reply, "session_id": session_id})

    async def _handle_health(self, _request: web.Request) -> web.Response:
        """Handle GET /api/health."""
        return web.json_response({"status": "ok"})
