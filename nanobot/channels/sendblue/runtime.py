"""Direct-message text transport over Sendblue's HTTPS API and receive webhook."""

from __future__ import annotations

import asyncio
import hmac
import re
from collections import OrderedDict
from typing import Any

import httpx
from aiohttp import web
from pydantic import BaseModel, Field, ValidationError

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

_PHONE = re.compile(r"\+[1-9][0-9]{6,14}\Z")


class SendblueConfig(Base):
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    from_number: str = ""
    webhook_secret: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=3980, ge=1, le=65535)
    allow_from: list[str] = Field(default_factory=list)

    def validate_runtime(self) -> None:
        if not all((self.api_key.strip(), self.api_secret.strip(), self.webhook_secret.strip())):
            raise ValueError("Sendblue requires apiKey, apiSecret and webhookSecret")
        if not _PHONE.fullmatch(self.from_number):
            raise ValueError("Sendblue fromNumber must be an E.164 phone number")
        if not self.allow_from or any(
            value != "*" and not _PHONE.fullmatch(value) for value in self.allow_from
        ):
            raise ValueError("Sendblue allowFrom must contain E.164 numbers or explicit '*'")


class _Incoming(BaseModel):
    # Strict fields avoid accepting truthy strings as direction flags.
    message_handle: str = Field(min_length=1, max_length=256)
    is_outbound: bool = Field(strict=True)
    from_number: str
    to_number: str
    content: str | None = None
    media_url: str | None = None
    group_id: str | None = None
    status: str


class _SendResult(BaseModel):
    message_handle: str = Field(min_length=1)
    status: str
    error_code: str | int | None = None


class SendblueChannel(BaseChannel):
    name = "sendblue"
    display_name = "Sendblue (iMessage / SMS)"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SendblueConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        parsed = SendblueConfig.model_validate(config) if isinstance(config, dict) else config
        super().__init__(parsed, bus)
        self.config: SendblueConfig = parsed
        self._client: httpx.AsyncClient | None = None
        self._runner: web.AppRunner | None = None
        self._stopped = asyncio.Event()
        self._lock = asyncio.Lock()
        self._seen: OrderedDict[str, None] = OrderedDict()

    def progress_transport_defaults(self) -> tuple[bool, bool]:
        return False, False

    def should_retry_send_error(self, error: Exception) -> bool:
        # A timed-out POST may already have delivered; Sendblue has no idempotency key.
        return False

    async def start(self) -> None:
        self.config.validate_runtime()
        self._stopped.clear()
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=False)
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_post("/sendblue/webhook", self._receive)
        self._runner = web.AppRunner(app, access_log=None)
        try:
            await self._runner.setup()
            await web.TCPSite(self._runner, self.config.host, self.config.port).start()
            self._running = True
            self.logger.info("Sendblue webhook listening on {}:{}", self.config.host, self.config.port)
            await self._stopped.wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._running = False
        self._stopped.set()
        if self._runner is not None:
            runner, self._runner = self._runner, None
            await runner.cleanup()
        if self._client is not None:
            client, self._client = self._client, None
            await client.aclose()

    async def _receive(self, request: web.Request) -> web.Response:
        if not self._running:
            return web.Response(status=503)
        supplied = request.headers.get("sb-signing-secret", "")
        if not hmac.compare_digest(supplied.encode(), self.config.webhook_secret.encode()):
            return web.Response(status=401)
        try:
            event = _Incoming.model_validate_json(await request.read())
        except ValidationError:
            return web.Response(status=400)
        if (
            event.is_outbound or event.group_id or event.status != "RECEIVED"
            or event.to_number != self.config.from_number
            or not _PHONE.fullmatch(event.from_number)
            or not self.is_allowed(event.from_number)
        ):
            return web.Response(status=204)
        content = event.content or ""
        if event.media_url:
            # Do not fetch untrusted attachment URLs. This channel handles text only.
            content += "\n[Attachment received; Sendblue channel supports text only.]"
        if not content.strip():
            return web.Response(status=204)
        async with self._lock:
            if event.message_handle in self._seen:
                return web.Response(status=204)
            await self._handle_message(
                sender_id=event.from_number, chat_id=event.from_number, content=content,
                metadata={"message_id": event.message_handle},
            )
            self._seen[event.message_handle] = None
            if len(self._seen) > 4096:
                self._seen.popitem(last=False)
        return web.Response(status=204)

    async def send(self, msg: OutboundMessage) -> None:
        if self._client is None or not self._running:
            raise RuntimeError("Sendblue channel is not running")
        if not _PHONE.fullmatch(msg.chat_id):
            raise ValueError("Sendblue recipient must be an E.164 phone number")
        if msg.media:
            raise ValueError("Sendblue channel supports text only; attachments were not sent")
        for chunk in split_message(msg.content, 2000):
            response = await self._client.post(
                "https://api.sendblue.com/api/send-message",
                headers={"sb-api-key-id": self.config.api_key,
                         "sb-api-secret-key": self.config.api_secret},
                json={"from_number": self.config.from_number, "number": msg.chat_id,
                      "content": chunk},
            )
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Sendblue send failed (HTTP {response.status_code})")
            try:
                result = _SendResult.model_validate_json(response.content)
            except ValidationError:
                raise RuntimeError("Sendblue returned an invalid send response") from None
            if result.error_code not in (None, 0) or result.status not in {
                "QUEUED", "SENT", "DELIVERED", "READ"
            }:
                raise RuntimeError("Sendblue did not accept the message")
