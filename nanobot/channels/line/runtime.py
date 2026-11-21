"""LINE channel implementation using LINE Messaging API webhook."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pydantic import Field, field_validator

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.pairing import is_approved
from nanobot.utils.helpers import safe_filename, split_message


_LINE_MAX_MESSAGE_LENGTH = 5000
_LINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_LINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_LINE_CODE_RE = re.compile(r"```(?:\w+)?\n?([\s\S]*?)```")
_LINE_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


class LineSettings(Base):
    channel_access_token: str = Field(..., alias="channelAccessToken")
    channel_secret: str = Field(..., alias="channelSecret")
    allow_from: list[str] | None = Field(default=None, alias="allowFrom")
    group_policy: str = Field(default="mention", alias="groupPolicy")
    webhook_path: str = "/line/webhook"
    webhook_port: int = 8088

    @field_validator("channel_access_token")
    @classmethod
    def _token_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("channelAccessToken must not be empty")
        return v


@dataclass
class _Run:
    text: str
    styles: frozenset[str] = field(default_factory=frozenset)
    opaque: bool = False


def _line_markdown_to_text(md_text: str) -> str:
    """Convert basic Markdown to LINE plain text.

    LINE supports limited formatting via Unicode characters.
    Falls back to plain text with no special formatting.
    """
    # Remove code blocks
    text = _LINE_CODE_RE.sub(r"\1", md_text)
    # Remove inline code markers
    text = _LINE_INLINE_CODE_RE.sub(r"\1", text)
    # Convert bold markers to plain
    text = _LINE_BOLD_RE.sub(r"\1", text)
    # Convert links: [text](url) -> text (url)
    text = _LINE_LINK_RE.sub(r"\1 (\2)", text)
    return text.strip()


def _segment_line_reply(text: str, max_len: int = _LINE_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a reply into LINE-friendly segments."""
    if len(text) <= max_len:
        return [text]
    segments = []
    while len(text) > max_len:
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = text.rfind(" ", 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        segments.append(text[:split_pos].rstrip())
        text = text[split_pos:].lstrip()
    segments.append(text.rstrip())
    return [s for s in segments if s]


class LineChannel(BaseChannel):
    """LINE Messaging API channel using webhook + aiohttp server."""

    def __init__(self, settings: LineSettings, bus: MessageBus) -> None:
        super().__init__(channel_name="line", bus=bus)
        self._settings = settings
        self._server: asyncio.AbstractServer | None = None

    @asynccontextmanager
    async def run(
        self,
        outbound: AsyncIterator[OutboundMessage],
        handle_inbound: None = None,
    ) -> AsyncIterator[None]:
        from linebot.v3 import WebhookHandler
        from linebot.v3.exceptions import InvalidSignatureError
        from linebot.v3.messaging import (
            ApiClient,
            Configuration,
            MessagingApi,
            ReplyMessageRequest,
            TextMessage,
        )
        from linebot.v3.webhooks import MessageEvent, TextMessageContent

        from aiohttp import web

        settings = self._settings
        app = web.Application()
        routes = web.RouteTableDef()

        # LINE API client
        config = Configuration(access_token=settings.channel_access_token)
        api_client = ApiClient(config)
        messaging_api = MessagingApi(api_client)
        handler = WebhookHandler(settings.channel_secret)

        @routes.post(settings.webhook_path)
        async def webhook(request: web.Request) -> web.Response:
            """Handle LINE webhook callback."""
            signature = request.headers.get("x-line-signature", "")
            body = await request.text()

            # Validate signature
            if not _validate_signature(settings.channel_secret, body, signature):
                logger.warning("[LINE] Invalid webhook signature")
                return web.Response(status=403)

            try:
                events = handler.parse(body, signature)
            except InvalidSignatureError:
                logger.warning("[LINE] Invalid webhook signature")
                return web.Response(status=403)

            for event in events:
                if not isinstance(event, MessageEvent):
                    continue
                if not isinstance(event.message, TextMessageContent):
                    continue

                user_id = event.source.user_id
                text = event.message.text

                if not is_approved(user_id, settings.allow_from):
                    logger.info("[LINE] Unapproved sender: {}", user_id)
                    continue

                logger.info("[LINE] Message from {}: {}", user_id, text[:100])

                # Queue inbound message
                await self._bus.publish(
                    InboundMessage(
                        channel="line",
                        sender=user_id,
                        text=text,
                        reply_token=event.reply_token,
                        source_event=event,
                    )
                )

            return web.Response(status=200)

        app.add_routes(routes)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
        await site.start()

        logger.info(
            "[LINE] Webhook server started on port {} (path={})",
            settings.webhook_port,
            settings.webhook_path,
        )

        try:
            async for message in outbound:
                if not isinstance(message, OutboundMessage):
                    continue
                reply_token = getattr(message, "reply_token", None)
                if reply_token:
                    text = _line_markdown_to_text(message.text)
                    segments = _segment_line_reply(text)
                    for seg in segments:
                        try:
                            messaging_api.reply_message(
                                ReplyMessageRequest(
                                    reply_token=reply_token,
                                    messages=[TextMessage(text=seg)],
                                )
                            )
                        except Exception as exc:
                            logger.error("[LINE] Failed to reply: {}", exc)
                elif message.target:
                    # Push message to a specific user
                    text = _line_markdown_to_text(message.text)
                    segments = _segment_line_reply(text)
                    for seg in segments:
                        try:
                            from linebot.v3.messaging import PushMessageRequest

                            messaging_api.push_message(
                                PushMessageRequest(
                                    to=message.target,
                                    messages=[TextMessage(text=seg)],
                                )
                            )
                        except Exception as exc:
                            logger.error("[LINE] Failed to push to {}: {}", message.target, exc)

            yield
        finally:
            await runner.cleanup()
            api_client.close()
            logger.info("[LINE] Webhook server stopped")


def _validate_signature(secret: str, body: str, signature: str) -> bool:
    """Validate LINE webhook signature using HMAC-SHA256."""
    if not signature:
        return False
    computed = hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected = computed.hex()
    return hmac.compare_digest(expected, signature)
