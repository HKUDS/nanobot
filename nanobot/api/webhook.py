"""Webhook HTTP server for external notifications."""

import secrets

from aiohttp import web
from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


class WebhookServer:
    """Fire-and-forget webhook endpoint that injects messages into the bus."""

    def __init__(
        self,
        bus: MessageBus,
        host: str = "0.0.0.0",
        port: int = 18790,
        secret: str = "",
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self.bus = bus
        self.host = host
        self.port = port
        self.default_channel = default_channel
        self.default_chat_id = default_chat_id
        self._runner: web.AppRunner | None = None

        if secret:
            self.secret = secret
            self.ephemeral = False
        else:
            self.secret = secrets.token_urlsafe(24)
            self.ephemeral = True

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/notify", self._handle_notify)
        app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Webhook server listening on {}:{}", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_notify(self, request: web.Request) -> web.Response:
        # Auth
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.secret:
            return web.json_response({"error": "unauthorized"}, status=401)

        # Parse body
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON body"}, status=400)

        message = body.get("message")
        if not message or not isinstance(message, str):
            return web.json_response({"error": "missing or invalid 'message' field"}, status=400)

        channel = body.get("channel") or self.default_channel
        chat_id = body.get("chat_id") or self.default_chat_id

        if not channel or not chat_id:
            return web.json_response(
                {"error": "no destination: provide 'channel' and 'chat_id' in payload or configure defaults"},
                status=400,
            )

        # Publish to bus as a system-channel message
        await self.bus.publish_inbound(
            InboundMessage(
                channel="system",
                sender_id="webhook",
                chat_id=f"{channel}:{chat_id}",
                content=message,
            )
        )

        logger.debug("Webhook accepted message for {}:{}", channel, chat_id)
        return web.json_response({"status": "accepted"}, status=202)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})
