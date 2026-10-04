"""Authenticated HTTP ingress for messages that bypass the agent loop."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, cast

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import DirectDeliveryConfig


class DirectDeliveryError(Exception):
    """A request error safe to return to the webhook caller."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class DirectDeliveryGuard:
    """Validate signatures and retain a bounded replay/rate-limit window."""

    config: DirectDeliveryConfig
    _seen: dict[str, int] = field(default_factory=dict)
    _request_times: list[int] = field(default_factory=list)

    def authenticate(self, headers: dict[str, str], body: bytes, *, now: int) -> str:
        timestamp = self._required_header(headers, "x-nanobot-timestamp")
        request_id = self._required_header(headers, "x-nanobot-request-id")
        signature = self._required_header(headers, "x-nanobot-signature-256")

        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise DirectDeliveryError(401, "invalid timestamp") from exc
        if abs(now - sent_at) > self.config.max_age_seconds:
            raise DirectDeliveryError(401, "stale request")

        expected = hmac.new(
            self.config.secret.encode(),
            f"{timestamp}.{request_id}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        supplied = signature.removeprefix("sha256=")
        if not hmac.compare_digest(supplied, expected):
            raise DirectDeliveryError(401, "invalid signature")

        self._prune(now)
        if request_id in self._seen:
            raise DirectDeliveryError(409, "duplicate request")
        if len(self._request_times) >= self.config.max_requests_per_minute:
            raise DirectDeliveryError(429, "rate limit exceeded")
        self._seen[request_id] = now
        self._request_times.append(now)
        return request_id

    @staticmethod
    def _required_header(headers: dict[str, str], key: str) -> str:
        value = headers.get(key, "").strip()
        if not value:
            raise DirectDeliveryError(401, f"missing {key} header")
        return value

    def _prune(self, now: int) -> None:
        replay_cutoff = now - self.config.max_age_seconds
        self._seen = {
            request_id: timestamp
            for request_id, timestamp in self._seen.items()
            if timestamp >= replay_cutoff
        }
        rate_cutoff = now - 60
        self._request_times = [timestamp for timestamp in self._request_times if timestamp > rate_cutoff]


def parse_delivery_body(body: bytes) -> str:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectDeliveryError(400, "body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise DirectDeliveryError(400, "body must be a JSON object")
    record = cast(dict[str, object], payload)
    if set(record) != {"content"}:
        raise DirectDeliveryError(400, "body must contain only content")
    content = record.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DirectDeliveryError(400, "content must be a non-empty string")
    if len(content) > 50_000:
        raise DirectDeliveryError(400, "content is too long")
    return content.strip()


def signed_delivery_headers(
    secret: str,
    request_id: str,
    body: bytes,
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Build headers for clients and tests using the documented signature format."""
    sent_at = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(
        secret.encode(),
        f"{sent_at}.{request_id}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Nanobot-Timestamp": sent_at,
        "X-Nanobot-Request-ID": request_id,
        "X-Nanobot-Signature-256": f"sha256={signature}",
    }


async def run_direct_delivery_server(
    config: DirectDeliveryConfig,
    bus: MessageBus,
) -> None:
    """Serve the direct-delivery endpoint until the surrounding task is cancelled."""
    guard = DirectDeliveryGuard(config)

    async def respond(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
                  405: "Method Not Allowed", 409: "Conflict", 413: "Content Too Large",
                  429: "Too Many Requests"}.get(status, "Error")
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )
        await writer.drain()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                header_data = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"),
                    timeout=5,
                )
            except asyncio.LimitOverrunError as exc:
                raise DirectDeliveryError(413, "headers too large") from exc
            if len(header_data) > 16_384:
                raise DirectDeliveryError(413, "headers too large")
            lines = header_data[:-4].decode("latin-1").split("\r\n")
            request = lines[0].split(" ")
            if len(request) < 2 or request[0] != "POST":
                raise DirectDeliveryError(405, "POST required")
            request_path = request[1].split("?", 1)[0]
            if request_path != config.path:
                raise DirectDeliveryError(404, "not found")
            headers = {
                key.strip().lower(): value.strip()
                for line in lines[1:]
                if ":" in line
                for key, value in [line.split(":", 1)]
            }
            try:
                length = int(headers.get("content-length", ""))
            except ValueError as exc:
                raise DirectDeliveryError(400, "valid content-length required") from exc
            if length < 1 or length > config.max_body_bytes:
                raise DirectDeliveryError(413, "body too large")
            body = await asyncio.wait_for(reader.readexactly(length), timeout=5)
            content = parse_delivery_body(body)
            request_id = guard.authenticate(headers, body, now=int(time.time()))
            await bus.publish_outbound(OutboundMessage(
                channel=config.channel,
                chat_id=config.chat_id,
                content=content,
                metadata={"direct_delivery": True, "request_id": request_id},
            ))
            await respond(writer, 200, {"ok": True, "request_id": request_id})
        except DirectDeliveryError as exc:
            await respond(writer, exc.status, {"ok": False, "error": exc.message})
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            await respond(writer, 400, {"ok": False, "error": "invalid HTTP request"})
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, config.host, config.port)
    async with server:
        await server.serve_forever()
