"""Twilio WhatsApp channel — webhook-based, pure-Python, no bridge needed.

Uses the official Twilio WhatsApp Business API:
- Inbound:  Twilio POSTs webhook to the gateway's HTTP server
- Outbound: Messages sent via the Twilio REST API

Install:  pip install nanobot-ai[twilio]
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

try:
    from twilio.request_validator import RequestValidator
    from twilio.rest import Client as TwilioClient

    _HAS_TWILIO = True
except ImportError:
    TwilioClient = None  # type: ignore[assignment,misc]
    RequestValidator = None  # type: ignore[assignment,misc]
    _HAS_TWILIO = False

# Twilio WhatsApp body limit (1600 chars)
TWILIO_MAX_MESSAGE_LEN = 1600
# Default gateway port (matches GatewayConfig.port in config/schema.py)
DEFAULT_GATEWAY_PORT = 18790


class TwilioWhatsAppConfig(Base):
    """Twilio WhatsApp channel configuration."""

    enabled: bool = False
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""  # e.g. "whatsapp:+14155238886"
    webhook_path: str = "/twilio/whatsapp"
    webhook_port: int = 0  # 0 = use gateway port (config.gateway.port)
    validate_signature: bool = False
    public_url: str = ""  # e.g. "https://abcd.ngrok-free.app" — used to reconstruct the signed URL
    allow_from: list[str] = Field(default_factory=list)  # ["+1234567890"] or ["*"]
    immediate_response: str = ""  # If set, reply with this message in TwiML before agent processes
    group_policy: Literal["open", "mention"] = "open"


class TwilioWhatsAppChannel(BaseChannel):
    """WhatsApp channel via Twilio Business API.

    Runs an aiohttp server to receive Twilio webhooks and sends replies
    via the Twilio REST API.
    """

    name = "twilio_whatsapp"
    display_name = "Twilio WhatsApp"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return TwilioWhatsAppConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = TwilioWhatsAppConfig.model_validate(config)
        super().__init__(config, bus)

        if not _HAS_TWILIO:
            raise ImportError(
                "Twilio SDK not installed. Install with: pip install nanobot-ai[twilio]"
            )

        self._account_sid: str = config.account_sid
        self._auth_token: str = config.auth_token
        self._from_number: str = config.from_number
        self._validate_sig: bool = config.validate_signature
        self._public_url: str = config.public_url.rstrip("/")
        self._webhook_path: str = config.webhook_path
        self._webhook_port: int = config.webhook_port
        self._immediate_response: str = config.immediate_response

        self._twilio: TwilioClient = TwilioClient(self._account_sid, self._auth_token)
        self._validator: RequestValidator | None = (
            RequestValidator(self._auth_token) if self._validate_sig else None
        )
        self._runner: Any = None  # aiohttp.web.AppRunner

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start an aiohttp server to receive Twilio webhooks."""
        from aiohttp import web

        app = web.Application()
        app.router.add_post(self._webhook_path, self._handle_webhook)
        app.router.add_get("/health", self._health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        port = self._webhook_port or DEFAULT_GATEWAY_PORT
        site = web.TCPSite(self._runner, "0.0.0.0", port)
        await site.start()

        self._running = True
        self._stop_event = asyncio.Event()
        logger.info(
            "Twilio WhatsApp webhook listening on :{}{}", port, self._webhook_path,
        )

        # Block until stop() is called
        await self._stop_event.wait()

        await self._runner.cleanup()
        self._runner = None

    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        self._stop_event.set()

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via the Twilio REST API."""
        if not msg.content and not msg.media:
            return

        to = msg.chat_id  # "whatsapp:+1234567890"

        # Send text (split if over Twilio limit)
        if msg.content:
            for chunk in split_message(msg.content, max_len=TWILIO_MAX_MESSAGE_LEN):
                await asyncio.to_thread(
                    self._twilio.messages.create,
                    from_=self._from_number,
                    to=to,
                    body=chunk,
                )

        # Send media (Twilio accepts publicly-accessible URLs)
        for media_path in msg.media or []:
            if media_path.startswith(("http://", "https://")):
                await asyncio.to_thread(
                    self._twilio.messages.create,
                    from_=self._from_number,
                    to=to,
                    media_url=[media_path],
                )
            else:
                logger.warning(
                    "Twilio WhatsApp cannot send local files directly ({}). "
                    "Provide a public URL instead.",
                    media_path,
                )

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: Any) -> Any:
        """Handle an incoming Twilio WhatsApp webhook POST."""
        from aiohttp import web

        form = await request.post()

        # Signature validation
        if self._validator:
            signature = request.headers.get("X-Twilio-Signature", "")
            # Use public_url if configured (needed behind proxies/ngrok),
            # otherwise fall back to the request URL as seen by the server.
            if self._public_url:
                url = self._public_url + request.path
            else:
                url = str(request.url)
            if not self._validator.validate(url, dict(form), signature):
                logger.warning("Invalid Twilio signature — rejecting request")
                return web.Response(status=403, text="Invalid signature")

        sender = form.get("From", "")  # "whatsapp:+1234567890"
        body = form.get("Body", "")
        message_sid = form.get("MessageSid", "")
        profile_name = form.get("ProfileName", "")

        # Download media attachments
        try:
            num_media = int(form.get("NumMedia", "0"))
        except (ValueError, TypeError):
            num_media = 0
        media_files: list[str] = []
        if num_media > 0:
            media_urls = [form.get(f"MediaUrl{i}", "") for i in range(num_media)]
            media_urls = [u for u in media_urls if u]
            media_files = await self._download_media(media_urls)

        # Build content with media tags (matches existing whatsapp.py convention)
        content = body or ""
        for fpath in media_files:
            mime, _ = mimetypes.guess_type(fpath)
            tag = "image" if mime and mime.startswith("image/") else "file"
            media_tag = f"[{tag}: {fpath}]"
            content = f"{content}\n{media_tag}" if content else media_tag

        if not content:
            content = "(empty message)"

        # sender_id for is_allowed check — strip "whatsapp:" prefix for readability
        sender_id = sender.replace("whatsapp:", "")

        logger.info(
            "Twilio WhatsApp from {} ({}): {} ({} media)",
            sender_id, profile_name, body[:80], num_media,
        )

        await self._handle_message(
            sender_id=sender_id,
            chat_id=sender,  # Keep full "whatsapp:+..." for Twilio replies
            content=content,
            media=media_files,
            metadata={
                "message_sid": message_sid,
                "profile_name": profile_name,
            },
        )

        # Return TwiML — actual reply comes via REST API
        if self._immediate_response:
            twiml = f"<Response><Message>{self._immediate_response}</Message></Response>"
        else:
            twiml = "<Response></Response>"
        return web.Response(text=twiml, content_type="application/xml")

    async def _health(self, request: Any) -> Any:
        from aiohttp import web

        return web.json_response({"status": "ok", "channel": self.name})

    # ------------------------------------------------------------------
    # Media helpers
    # ------------------------------------------------------------------

    async def _download_media(self, media_urls: list[str]) -> list[str]:
        """Download Twilio media attachments (requires Basic Auth) to media dir."""
        import httpx

        media_dir = get_media_dir("twilio_whatsapp")
        media_dir.mkdir(parents=True, exist_ok=True)

        paths: list[str] = []
        try:
            async with httpx.AsyncClient(
                auth=(self._account_sid, self._auth_token),
                follow_redirects=True,
                timeout=30.0,
            ) as client:
                for url in media_urls:
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()

                        content_type = resp.headers.get(
                            "content-type", "application/octet-stream"
                        )
                        ext = mimetypes.guess_extension(content_type) or ".bin"

                        # Use message SID from URL as a stable filename
                        sid = url.rstrip("/").rsplit("/", 1)[-1]
                        file_path = media_dir / f"{sid}{ext}"
                        file_path.write_bytes(resp.content)
                        paths.append(str(file_path))
                        logger.debug("Downloaded media to {} ({})", file_path, content_type)
                    except Exception as e:
                        logger.error("Failed to download media {}: {}", url, e)
        except Exception as e:
            logger.error("Media download client error: {}", e)

        return paths
