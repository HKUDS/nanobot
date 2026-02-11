"""Zalo Bot Platform channel implementation using Webhook mode.

Integrates with the Zalo Bot API at https://bot-api.zaloplatforms.com.
Receives events via webhook (HTTP POST) and sends replies via the
sendMessage / sendPhoto APIs.

Reference docs:
- Webhook:     https://bot.zaloplatforms.com/docs/webhook/
- setWebhook:  https://bot.zaloplatforms.com/docs/apis/setWebhook/
- sendMessage: https://bot.zaloplatforms.com/docs/apis/sendMessage/
- sendPhoto:   https://bot.zaloplatforms.com/docs/apis/sendPhoto/
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ZaloConfig

# Base URL for the Zalo Bot API (token is embedded in path)
ZALO_BOT_API = "https://bot-api.zaloplatforms.com/bot"

# Maximum text length per Zalo message
MAX_TEXT_LEN = 2000


class ZaloChannel(BaseChannel):
    """Zalo Bot Platform channel using webhook mode.

    Lifecycle
    ---------
    1. ``start()`` launches a lightweight ``uvicorn`` ASGI server that
       listens for Zalo webhook POST requests.
    2. Inbound events are verified via the ``X-Bot-Api-Secret-Token``
       header and forwarded to the nanobot message bus.
    3. ``send()`` calls the Zalo Bot API (``sendMessage`` / ``sendPhoto``)
       to deliver replies back to the originating chat.
    """

    name = "zalo"

    def __init__(self, config: ZaloConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config: ZaloConfig = config
        self._http: httpx.AsyncClient | None = None
        self._server_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _api_base(self) -> str:
        """Return the bot-specific API base URL."""
        return f"{ZALO_BOT_API}{self.config.bot_token}"

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the webhook HTTP server to receive Zalo events."""
        if not self.config.bot_token:
            logger.error("Zalo bot_token is not configured – channel will not start")
            return

        if not self.config.webhook_secret:
            logger.error("Zalo webhook_secret is required (8-256 chars) – channel will not start")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        # Build the FastAPI app for the webhook endpoint
        app = self._build_app()

        # Start uvicorn as an async task so it does not block the event loop
        import uvicorn

        uvicorn_config = uvicorn.Config(
            app=app,
            host=self.config.webhook_host,
            port=self.config.webhook_port,
            log_level="info",
        )
        server = uvicorn.Server(uvicorn_config)

        logger.info(
            "Zalo webhook server starting on {}:{}{}",
            self.config.webhook_host,
            self.config.webhook_port,
            self.config.webhook_path,
        )

        # Run the server (blocks until shutdown)
        await server.serve()

    async def stop(self) -> None:
        """Stop the Zalo channel and close the HTTP client."""
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("Zalo channel stopped")

    # ------------------------------------------------------------------
    # FastAPI webhook application
    # ------------------------------------------------------------------

    def _build_app(self) -> Any:
        """Build and return a FastAPI ASGI app with the webhook route."""
        app = FastAPI(title="Nanobot Zalo Webhook", docs_url=None, redoc_url=None)

        @app.post(self.config.webhook_path)
        async def webhook_handler(request: Request) -> JSONResponse:
            """Handle incoming Zalo webhook events."""
            # 1. Verify secret token
            incoming_secret = request.headers.get("x-bot-api-secret-token", "")
            if incoming_secret != self.config.webhook_secret:
                logger.warning("Zalo webhook: invalid secret token – rejecting request")
                return JSONResponse(
                    status_code=403,
                    content={"message": "Unauthorized"},
                )

            # 2. Parse the JSON body
            try:
                # Zalo sends standard JSON
                body: dict[str, Any] = await request.json()
            except Exception as exc:
                logger.error("Zalo webhook: failed to parse body – {}", exc)
                return JSONResponse(
                    status_code=400,
                    content={"message": "Bad Request"},
                )

            # 3. Process the event asynchronously (do not block the response)
            asyncio.create_task(self._process_event(body))

            # 4. Respond quickly to Zalo (< 2s)
            return JSONResponse(content={"message": "OK"})

        @app.get("/health")
        async def health_check() -> JSONResponse:
            """Simple health-check endpoint."""
            return JSONResponse(content={"status": "ok", "channel": "zalo"})

        return app

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    async def _process_event(self, body: dict[str, Any]) -> None:
        """Parse a Zalo webhook payload and forward it to the message bus.

        Payload schema (from Zalo docs):
        {
          "ok": true,
          "result": {
            "event_name": "message.text.received",
            "message": {
              "from": {"id": "...", "display_name": "...", "is_bot": false},
              "chat": {"id": "...", "chat_type": "PRIVATE"},
              "text": "...",
              "message_id": "...",
              "date": 1750316131602
            }
          }
        }
        """
        try:
            # Depending on Zalo API version, payload might be wrapped differently.
            # Usually Zalo sends {"event_name": "...", "message": ...} at root?
            # Or {"error": 0, "message": "Success", "data": ...}?
            #
            # Based on user logs:
            # Body: {"event_name":"message.text.received","message":{...}}
            #
            # So it is NOT wrapped in "result" key at the top level in the webhook call?
            # Wait, the user log showed:
            # Body: {"event_name":"message.text.received","message":{...}}
            #
            # My previous code expected:
            # result = body.get("result", {})
            # event_name = result.get("event_name")
            # This would fail if "event_name" is at root.

            # Let's support both structures just in case.
            event_name = body.get("event_name", "")
            message = body.get("message", {})

            if not event_name and "result" in body:
                result = body["result"]
                event_name = result.get("event_name", "")
                message = result.get("message", {})

            if not message:
                logger.debug("Zalo webhook: no message in payload – event={}", event_name)
                return

            sender_info: dict[str, Any] = message.get("from", {})
            chat_info: dict[str, Any] = message.get("chat", {})

            sender_id: str = sender_info.get("id", "")
            chat_id: str = chat_info.get("id", "")
            chat_type: str = chat_info.get("chat_type", "PRIVATE")
            display_name: str = sender_info.get("display_name", "Unknown")
            is_bot: bool = sender_info.get("is_bot", False)

            # Ignore messages from bots (prevent loops)
            if is_bot:
                logger.debug("Zalo: ignoring bot message from {}", sender_id)
                return

            if not sender_id or not chat_id:
                logger.warning("Zalo: missing sender_id or chat_id in event {}", event_name)
                return

            # Extract content based on event type
            content = ""
            media: list[str] = []

            if event_name == "message.text.received":
                content = message.get("text", "")
            elif event_name == "message.image.received":
                photo_url = message.get("photo", "")
                caption = message.get("caption", "")
                content = caption or "[Image received]"
                if photo_url:
                    media.append(photo_url)
            elif event_name == "message.sticker.received":
                logger.debug("Zalo: sticker received from {} – skipping", display_name)
                return
            elif event_name == "message.unsupported.received":
                logger.debug("Zalo: unsupported message type from {} – skipping", display_name)
                return
            else:
                logger.debug("Zalo: unhandled event_name={}", event_name)
                return

            if not content:
                logger.debug("Zalo: empty content from {} – skipping", display_name)
                return

            logger.info(
                "Zalo inbound [{}] from {} ({}): {}",
                chat_type,
                display_name,
                sender_id,
                content[:80],
            )

            # Forward to nanobot message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media if media else None,
                metadata={
                    "platform": "zalo",
                    "sender_name": display_name,
                    "chat_type": chat_type,
                    "event_name": event_name,
                    "message_id": message.get("message_id", ""),
                },
            )

        except Exception as exc:
            logger.exception("Zalo: error processing webhook event – {}", exc)

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Send a reply back through the Zalo Bot API.

        Handles text chunking (2000 char limit) and photo sending.
        """
        if not self._http:
            logger.warning("Zalo HTTP client not initialized – cannot send")
            return

        content = msg.content or ""

        # Send text messages (chunked if necessary)
        if content:
            chunks = self._split_message(content, MAX_TEXT_LEN)
            for chunk in chunks:
                await self._send_text(msg.chat_id, chunk)

    async def _send_text(self, chat_id: str, text: str) -> None:
        """Send a single text message via the Zalo Bot API."""
        url = f"{self._api_base}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

        try:
            resp = await self._http.post(url, json=payload)  # type: ignore[union-attr]
            data = resp.json()
            if not data.get("ok"):
                logger.error(
                    "Zalo sendMessage failed: {} – {}",
                    data.get("error_code"),
                    data.get("description"),
                )
            else:
                logger.debug("Zalo message sent to {}", chat_id)
        except Exception as exc:
            logger.error("Zalo sendMessage error: {}", exc)

    async def _send_photo(self, chat_id: str, photo_url: str, caption: str = "") -> None:
        """Send a photo message via the Zalo Bot API."""
        url = f"{self._api_base}/sendPhoto"
        payload: dict[str, str] = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            payload["caption"] = caption[:MAX_TEXT_LEN]

        try:
            resp = await self._http.post(url, json=payload)  # type: ignore[union-attr]
            data = resp.json()
            if not data.get("ok"):
                logger.error(
                    "Zalo sendPhoto failed: {} – {}",
                    data.get("error_code"),
                    data.get("description"),
                )
            else:
                logger.debug("Zalo photo sent to {}", chat_id)
        except Exception as exc:
            logger.error("Zalo sendPhoto error: {}", exc)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _split_message(content: str, max_len: int = MAX_TEXT_LEN) -> list[str]:
        """Split a message into chunks that fit Zalo's character limit.

        Tries to split at newlines for cleaner formatting.
        """
        if len(content) <= max_len:
            return [content]

        chunks: list[str] = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break
            # Try to split at a newline within the limit
            split_idx = content.rfind("\n", 0, max_len)
            if split_idx == -1:
                # No newline found – hard split at max_len
                split_idx = max_len
            chunks.append(content[:split_idx])
            content = content[split_idx:].lstrip("\n")
        return chunks
