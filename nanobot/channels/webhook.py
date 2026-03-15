"""HTTP webhook channel — receives inbound messages via POST /event/{name}."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.channels.base import BaseChannel

try:
    from pydantic import ConfigDict
    from pydantic.alias_generators import to_camel
except ImportError:  # pragma: no cover
    pass


class _Base:
    """Tiny mixin so nested models use the same camelCase convention."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)  # type: ignore[misc]


# -- config models (parsed by the channel, not registered in global schema) --

from pydantic import BaseModel


class EndpointConfig(BaseModel, _Base):
    """A single named webhook endpoint."""

    prompt: str  # message template — may contain {payload}


class WebhookConfig(BaseModel, _Base):
    """Webhook channel configuration (lives under channels.webhook)."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8088
    secret: str | None = None
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    endpoints: dict[str, EndpointConfig] = Field(default_factory=dict)


# -- channel implementation ---------------------------------------------------


class WebhookChannel(BaseChannel):
    """HTTP webhook channel.

    Listens for ``POST /event/{name}`` requests and converts them into
    inbound messages on the nanobot message bus.
    """

    name = "webhook"
    display_name = "Webhook"

    def __init__(self, config: Any, bus: Any) -> None:
        if isinstance(config, dict):
            config = WebhookConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebhookConfig = config
        self._server: asyncio.Server | None = None

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.endpoints:
            logger.info("Webhook channel: no endpoints configured, skipping")
            return
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.config.host,
            port=self.config.port,
        )
        logger.info(
            "Webhook channel listening on {}:{} ({} endpoints)",
            self.config.host,
            self.config.port,
            len(self.config.endpoints),
        )
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            self._server = None

    async def send(self, msg: Any) -> None:
        # Webhook is inbound-only; outbound responses are delivered via
        # whichever channel the agent chooses (e.g. telegram, slack).
        pass

    # -- HTTP handling ---------------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._process_request(reader, writer)
        except Exception as exc:
            logger.warning("Webhook: unhandled error: {}", exc)
            try:
                self._send_response(writer, 500, {"error": "internal server error"})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Read request line + headers (up to 8 KB)
        raw = b""
        while True:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=10)
            if not chunk:
                break
            raw += chunk
            if b"\r\n\r\n" in raw or b"\n\n" in raw:
                break
            if len(raw) > 8192:
                self._send_response(writer, 400, {"error": "headers too large"})
                return

        text = raw.decode("utf-8", errors="replace")
        header_part, sep, body_part = text.partition("\r\n\r\n")
        if not sep:
            header_part, sep, body_part = text.partition("\n\n")

        lines = header_part.splitlines()
        if not lines:
            self._send_response(writer, 400, {"error": "empty request"})
            return

        parts = lines[0].split()
        if len(parts) < 2:
            self._send_response(writer, 400, {"error": "bad request line"})
            return
        method, path = parts[0], parts[1]

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()

        # Read remaining body
        body = body_part.encode("utf-8", errors="replace")
        content_length = int(headers.get("content-length", "0") or "0")
        remaining = content_length - len(body)
        if remaining > 0:
            extra = await asyncio.wait_for(reader.read(remaining), timeout=10)
            body += extra

        # Only POST allowed
        if method != "POST":
            self._send_response(writer, 405, {"error": "method not allowed"})
            return

        if not path.startswith("/event/"):
            self._send_response(writer, 404, {"error": "not found"})
            return

        event_name = path[len("/event/"):].strip("/")
        if not event_name:
            self._send_response(writer, 400, {"error": "missing event name"})
            return

        # Auth
        if self.config.secret:
            auth = headers.get("authorization", "")
            if auth != f"Bearer {self.config.secret}":
                self._send_response(writer, 401, {"error": "unauthorized"})
                return

        # Endpoint lookup
        endpoint = self.config.endpoints.get(event_name)
        if endpoint is None:
            self._send_response(writer, 404, {"error": f"unknown event '{event_name}'"})
            return

        # Build message from prompt template
        payload = body.decode("utf-8", errors="replace").strip()
        message = endpoint.prompt.replace("{payload}", payload) if payload else endpoint.prompt

        logger.info(
            "Webhook: event '{}' received ({} bytes payload)",
            event_name,
            len(payload),
        )

        # Publish to bus via BaseChannel._handle_message
        await self._handle_message(
            sender_id="webhook",
            chat_id=event_name,
            content=message,
        )

        self._send_response(writer, 200, {"status": "ok", "event": event_name})

    @staticmethod
    def _send_response(writer: asyncio.StreamWriter, status: int, body: dict) -> None:
        status_text = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
        }.get(status, "Unknown")
        payload = json.dumps(body).encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("utf-8") + payload
        writer.write(response)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebhookConfig().model_dump(by_alias=True)
