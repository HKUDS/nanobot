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
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import Field
from zalo_bot import Bot, Update
from zalo_bot.constants import ChatAction
from zalo_bot.ext import Dispatcher

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


class ZaloConfig(Base):
    """Zalo Bot Platform channel configuration.

    Uses the Zalo Bot API at https://bot-api.zaloplatforms.com.
    Bot token format: "12345689:abc-xyz" from https://bot.zaloplatforms.com.
    """

    enabled: bool = False
    mode: str = "webhook"  # "webhook" or "polling"
    bot_token: str = ""  # Bot token from Zalo Bot Platform
    webhook_secret: str = ""  # Secret for X-Bot-Api-Secret-Token verification (8-256 chars)
    webhook_path: str = "/webhooks/zalo"  # Path on which to receive webhook events
    webhook_host: str = "0.0.0.0"  # Host to bind the webhook server
    webhook_port: int = 8443  # Port for the webhook server (443, 80, 88, 8443)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs


# Maximum text length per Zalo message (safely below 2000 limit)
MAX_TEXT_LEN = 1600


class ZaloChannel(BaseChannel):
    """Zalo Bot Platform channel using webhook mode via python-zalo-bot SDK.

    Lifecycle
    ---------
    1. ``start()`` launches a lightweight ``uvicorn`` ASGI server that
       listens for Zalo webhook POST requests.
    2. Inbound events are verified via the ``X-Bot-Api-Secret-Token``
       header and parsed using ``Update.de_json``.
    3. They are then dispatched via ``Dispatcher`` or handled manually.
    4. ``send()`` uses ``bot.send_message``/``bot.send_photo`` to reply.
    """

    name = "zalo"
    display_name = "Zalo"

    def __init__(self, config: dict[str, Any], bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config = ZaloConfig.model_validate(config)
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self._server_task: asyncio.Task[None] | None = None
        # Track active typing tasks per chat_id to keep the indicator alive
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default config for Zalo channel."""
        return ZaloConfig(enabled=False).model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Zalo channel in either webhook or polling mode."""
        if not self.config.bot_token:
            logger.error("Zalo bot_token is not configured – channel will not start")
            return

        self._running = True
        self.bot = Bot(token=self.config.bot_token)
        self.dispatcher = Dispatcher(self.bot, None, workers=0)

        if self.config.mode == "polling":
            logger.info("Zalo (SDK) starting in POLLING mode")
            # Delete webhook first to ensure polling works
            try:
                await self.bot.delete_webhook()
            except Exception as e:
                logger.warning("Failed to delete Zalo webhook before polling: {}", e)

            # Start polling in a separate task
            self._server_task = asyncio.create_task(self._run_polling())
        else:
            logger.info("Zalo (SDK) starting in WEBHOOK mode")
            if not self.config.webhook_secret:
                logger.error("Zalo webhook_secret is required for webhook mode")
                return

            # Build and run FastAPI server
            app = self._build_app()
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
            await server.serve()

    async def _run_polling(self) -> None:
        """Run long polling for Zalo updates."""
        offset = 0
        while self._running:
            try:
                # Use SDK get_update or similar
                # Based on Example: update = await bot.get_update(timeout=60)
                update = await self.bot.get_update(timeout=30)
                if update:
                    await self._process_update(update)
            except Exception as e:
                logger.error("Zalo polling error: {}", e)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Zalo channel."""
        self._running = False
        logger.info("Zalo channel stopped")

    # ------------------------------------------------------------------
    # FastAPI webhook application
    # ------------------------------------------------------------------

    def _build_app(self) -> Any:
        """Build and return a FastAPI ASGI app with the webhook route."""
        app = FastAPI(title="Nanobot Zalo Webhook (SDK)", docs_url=None, redoc_url=None)

        @app.post(self.config.webhook_path)
        async def webhook_handler(request: Request) -> JSONResponse:
            """Handle incoming Zalo webhook events."""
            # 1. Verify secret token
            incoming_secret = request.headers.get("x-bot-api-secret-token", "")
            if incoming_secret != self.config.webhook_secret:
                logger.warning("Zalo webhook: invalid secret token")
                return JSONResponse(status_code=403, content={"message": "Unauthorized"})

            # 2. Parse the JSON body
            try:
                body: dict[str, Any] = await request.json()
                # The SDK expects the 'result' part for de_json if wrapped,
                # but if it's the raw update, we pass it as is.
                # Based on SDK example: Update.de_json(request.get_json()['result'], bot)
                data = body.get("result", body)
                update = Update.de_json(data, self.bot)

                if update:
                    # Process the update asynchronously
                    asyncio.create_task(self._process_update(update))

            except Exception as exc:
                logger.error("Zalo webhook processing error: {}", exc)
                return JSONResponse(status_code=400, content={"message": "Bad Request"})

            return JSONResponse(content={"message": "OK"})

        @app.get("/health")
        async def health_check() -> JSONResponse:
            return JSONResponse(content={"status": "ok", "channel": "zalo-sdk"})

        return app

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    async def _process_update(self, update: Update) -> None:
        """Process a parsed Update and forward to the message bus."""
        if not update.message:
            return

        sender = update.effective_user
        chat = update.message.chat

        if not sender or not chat:
            return

        if sender.is_bot:
            return

        # Extract text and media content first before starting indicators
        content = update.message.text or ""
        media: list[str] = []

        # Add support for photos from the SDK message
        # SDK Message class has photo_url slot, but let's be robust
        photo_url = update.message.photo_url
        if not photo_url and update.message.api_kwargs:
            # Fallback to 'photo' key which is common in Zalo API
            photo_url = update.message.api_kwargs.get("photo")

        if photo_url:
            media.append(photo_url)
            if not content:
                content = "[Image received]"

        # Handle sticker messages: acknowledge them with a friendly reply
        sticker = getattr(update.message, "sticker", None)
        if not sticker and update.message.api_kwargs:
            sticker = update.message.api_kwargs.get("sticker")

        if not content and not media and sticker:
            # Sticker received - treat as a greeting or acknowledgement
            content = "[Sticker received]"

        if not content and not media:
            # Truly empty message (e.g. unsupported event type) - skip silently
            return

        # Only start typing indicator after confirming we have valid content to process
        self._start_typing_indicator(chat.id)

        logger.info(
            "Zalo SDK inbound [{}] from {} ({}): {}",
            chat.type,
            sender.display_name,
            sender.id,
            content[:80],
        )

        # Forward to nanobot message bus
        await self._handle_message(
            sender_id=sender.id,
            chat_id=chat.id,
            content=content,
            media=media if media else None,
            metadata={
                "platform": "zalo",
                "sender_name": sender.display_name,
                "chat_type": chat.type,
                "message_id": update.message.message_id,
            },
        )

    # ------------------------------------------------------------------
    # Typing indicator management
    # ------------------------------------------------------------------

    def _start_typing_indicator(self, chat_id: str) -> None:
        """Start a periodic task to show typing indicator."""
        # Cancel existing task if any
        self._stop_typing_indicator(chat_id)

        # Create new periodic task
        async def _periodic_typing():
            try:
                # Send immediate signal
                if self.bot:
                    await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

                while True:
                    await asyncio.sleep(4)  # Zalo's typing status lasts ~5s
                    if self.bot:
                        logger.debug("Sending Zalo typing indicator to {}", chat_id)
                        await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Zalo typing indicator task failed for {}: {}", chat_id, e)

        task = asyncio.create_task(_periodic_typing())
        self._typing_tasks[chat_id] = task

    def _stop_typing_indicator(self, chat_id: str) -> None:
        """Stop the periodic typing task for a specific chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task:
            task.cancel()

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Send a reply through the Zalo Bot SDK."""
        if not self.bot:
            logger.warning("Zalo bot not initialized – cannot send")
            return

        # 1. Stop typing indicator
        self._stop_typing_indicator(msg.chat_id)

        content = msg.content or ""
        if not content:
            return

        # Convert Markdown to Unicode formatting for visual emphasis on Zalo
        # Zalo Bot API does not support parse_mode, so we use Unicode characters
        content = self._markdown_to_unicode(content)

        try:
            # 2. Send formatted message chunks
            # Zalo has a 2000 char limit.
            chunks = self._split_message(content, MAX_TEXT_LEN)
            logger.info("Splitting Zalo message into {} chunks", len(chunks))
            for i, chunk in enumerate(chunks):
                if i > 0:
                    await asyncio.sleep(0.5)  # Small delay to avoid burst limits
                await self.bot.send_message(
                    chat_id=msg.chat_id,
                    text=chunk,
                )
                logger.debug("Sent Zalo chunk {}/{} ({} chars)", i + 1, len(chunks), len(chunk))

            logger.info("Successfully sent all Zalo chunks to {}", msg.chat_id)

        except Exception as exc:
            logger.error("Zalo SDK send error: {}", exc)

    @staticmethod
    def _markdown_to_unicode(text: str) -> str:
        """Convert Markdown formatting to Unicode visual emphasis for platforms like Zalo.

        This approach is used when parse_mode (HTML/Markdown) is not supported.
        It converts common Markdown patterns to Unicode Mathematical Alphanumeric Symbols.
        """
        # Header Bold (Thick)
        HDR_UP = 0x1D400
        HDR_LOW = 0x1D41A
        HDR_DIG = 0x1D7CE

        # Sub Bold (Softer)
        SUB_UP = 0x1D5D4
        SUB_LOW = 0x1D5EE

        # Italic
        IT_UP = 0x1D434
        IT_LOW = 0x1D44E

        def transform(
            text: str, upper_base: int, lower_base: int, digit_base: int | None = None
        ) -> str:
            """Apply character transformation based on Unicode offsets."""
            result = []
            for char in text:
                if "A" <= char <= "Z":
                    result.append(chr(upper_base + ord(char) - ord("A")))
                elif "a" <= char <= "z":
                    result.append(chr(lower_base + ord(char) - ord("a")))
                elif digit_base and "0" <= char <= "9":
                    result.append(chr(digit_base + ord(char) - ord("0")))
                else:
                    result.append(char)
            return "".join(result)

        def header(match: re.Match) -> str:
            return transform(match.group(1), HDR_UP, HDR_LOW, HDR_DIG)

        def subheader(match: re.Match) -> str:
            return transform(match.group(1), SUB_UP, SUB_LOW)

        def italic(match: re.Match) -> str:
            return transform(match.group(1), IT_UP, IT_LOW)

        # =============================
        # FORMAT ORDER
        # =============================

        # ### Header (max bold)
        text = re.sub(r"^###\s+(.+)$", header, text, flags=re.MULTILINE)

        # ## Subheader
        text = re.sub(r"^##\s+(.+)$", subheader, text, flags=re.MULTILINE)

        # Bold **text**
        text = re.sub(r"\*\*(.+?)\*\*", header, text)

        # Italic *text*
        text = re.sub(r"\*(.+?)\*", italic, text)

        # Code block
        text = re.sub(r"`(.+?)`", r"「\1」", text)

        # Blockquote
        text = re.sub(r"^>\s+(.+)$", r"│ \1", text, flags=re.MULTILINE)

        # Unordered list
        text = re.sub(r"^\-\s+(.+)$", r"▸ \1", text, flags=re.MULTILINE)

        # Ordered list
        text = re.sub(r"^(\d+)\.\s+(.+)$", r"\1) \2", text, flags=re.MULTILINE)

        # Links
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f"🔗 {transform(m.group(1), HDR_UP, HDR_LOW)}\n{m.group(2)}",
            text,
        )

        return text

    @staticmethod
    def _split_message(content: str, max_len: int = MAX_TEXT_LEN) -> list[str]:
        """Split a message into chunks that fit Zalo's character limit."""
        if len(content) <= max_len:
            return [content]

        chunks: list[str] = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break
            split_idx = content.rfind("\n", 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(content[:split_idx])
            content = content[split_idx:].lstrip("\n")
        return chunks
