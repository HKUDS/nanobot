"""Generic bidirectional webhook channel implementation."""

from __future__ import annotations

import asyncio
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebhookConfig


class _WebhookRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that delegates route processing to WebhookChannel."""

    channel: "WebhookChannel"

    def do_POST(self) -> None:
        self._handle()

    def do_GET(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("Webhook HTTP {} - {}", self.address_string(), fmt % args)

    def _handle(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        body = self.rfile.read(content_length) if content_length > 0 else b""
        remote_addr = f"{self.client_address[0]}:{self.client_address[1]}"

        try:
            future = asyncio.run_coroutine_threadsafe(
                self.channel.handle_http_request(
                    method=self.command,
                    path=self.path,
                    headers=dict(self.headers.items()),
                    body=body,
                    remote_addr=remote_addr,
                ),
                self.channel.loop,
            )
            status, response_body = future.result(timeout=30)
        except Exception as e:
            logger.error("Webhook request handling failed: {}", e)
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            response_body = {"error": "Internal server error"}

        payload = json.dumps(response_body, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)


class WebhookChannel(BaseChannel):
    """Bidirectional local webhook channel."""

    name = "webhook"

    def __init__(self, config: WebhookConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WebhookConfig = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._webhook_path = self._normalize_path(self.config.webhook_path, "/v1/inbound")
        self._send_path = self._normalize_path(self.config.send_path, "/v1/outbound")

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("Webhook event loop is not initialized")
        return self._loop

    async def start(self) -> None:
        """Start webhook HTTP server."""
        if self._running:
            return

        host = (self.config.webhook_host or "127.0.0.1").strip() or "127.0.0.1"
        port = int(self.config.webhook_port or 18794)
        self._webhook_path = self._normalize_path(self.config.webhook_path, "/v1/inbound")
        self._send_path = self._normalize_path(self.config.send_path, "/v1/outbound")
        self._loop = asyncio.get_running_loop()

        handler_cls = self._build_handler_class()

        try:
            self._server = ThreadingHTTPServer((host, port), handler_cls)
            self._server.daemon_threads = True
        except OSError as e:
            logger.error("Failed to start webhook channel server: {}", e)
            return

        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="nanobot-webhook-server",
            daemon=True,
        )
        self._server_thread.start()
        self._running = True
        logger.info(
            "Webhook channel listening on http://{}:{}{} and http://{}:{}{}",
            host,
            port,
            self._webhook_path,
            host,
            port,
            self._send_path,
        )

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop webhook HTTP server."""
        self._running = False

        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5)
        self._server_thread = None

        logger.info("Webhook channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Forward outbound message from nanobot to the local connector."""
        to_value = str(msg.metadata.get("to") or msg.chat_id).strip()
        peer_value = str(msg.metadata.get("peer") or "").strip()
        content_value = str(msg.content or "")

        if not to_value or not content_value.strip():
            logger.warning("Webhook outbound send skipped: missing to/content")
            return

        payload: dict[str, str] = {
            "to": to_value,
            "content": content_value,
        }
        if peer_value:
            payload["peer"] = peer_value

        status, response = await self._forward_to_connector(payload)
        if status >= HTTPStatus.BAD_REQUEST:
            logger.error("Webhook outbound send failed: status={} error={}", status, response.get("error"))

    async def handle_http_request(
        self,
        method: str,
        path: str,
        headers: Mapping[str, Any],
        body: bytes,
        remote_addr: str,
    ) -> tuple[int, dict[str, Any]]:
        """Handle an incoming HTTP request for inbound/outbound routes."""
        route_path = urlsplit(path).path

        if route_path == self._webhook_path:
            return await self._handle_inbound(method, headers, body, remote_addr)
        if route_path == self._send_path:
            return await self._handle_send(method, headers, body)
        return HTTPStatus.NOT_FOUND, {"error": "Route not found"}

    async def _handle_inbound(
        self,
        method: str,
        headers: Mapping[str, Any],
        body: bytes,
        remote_addr: str,
    ) -> tuple[int, dict[str, Any]]:
        if method != "POST":
            return HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method not allowed"}
        if not self._is_json_content_type(headers):
            return HTTPStatus.BAD_REQUEST, {"error": "Content-Type must be application/json"}
        if not self._is_authorized(headers):
            return HTTPStatus.FORBIDDEN, {"error": "Invalid token"}

        payload = self._decode_json_body(body)
        if payload is None:
            return HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON payload"}

        sender_id = self._resolve_sender_id(headers, remote_addr)
        if not self.is_allowed(sender_id):
            return HTTPStatus.FORBIDDEN, {"error": "Sender not allowed"}

        chat_id = self._resolve_chat_id(headers, sender_id)
        content, payload_json = self._resolve_payload_content(payload)

        metadata: dict[str, Any] = {
            "platform": "webhook",
            "delivery_protocol": "webhook",
            "payload_json": payload_json,
            "content_type": self._header(headers, "Content-Type"),
            "request_id": self._header(headers, "x-request-id"),
            "sender_id": sender_id,
            "chat_id": chat_id,
        }
        for header_name in (
            "x-clawdentity-agent-did",
            "x-clawdentity-to-agent-did",
            "x-clawdentity-verified",
        ):
            value = self._header(headers, header_name)
            if value:
                metadata[header_name.replace("-", "_")] = value

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            metadata=metadata,
        )
        return HTTPStatus.ACCEPTED, {"status": "accepted"}

    async def _handle_send(
        self,
        method: str,
        headers: Mapping[str, Any],
        body: bytes,
    ) -> tuple[int, dict[str, Any]]:
        if method != "POST":
            return HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method not allowed"}
        if not self._is_json_content_type(headers):
            return HTTPStatus.BAD_REQUEST, {"error": "Content-Type must be application/json"}
        if not self._is_authorized(headers):
            return HTTPStatus.FORBIDDEN, {"error": "Invalid token"}

        payload = self._decode_json_body(body)
        if not isinstance(payload, dict):
            return HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON payload"}

        to_value = str(payload.get("to", "")).strip()
        content_value = payload.get("content")
        peer_value = payload.get("peer")

        if not to_value:
            return HTTPStatus.BAD_REQUEST, {"error": "Missing required field: to"}
        if not isinstance(content_value, str) or not content_value.strip():
            return HTTPStatus.BAD_REQUEST, {"error": "Missing required field: content"}

        outbound_payload: dict[str, str] = {
            "to": to_value,
            "content": content_value,
        }
        if isinstance(peer_value, str) and peer_value.strip():
            outbound_payload["peer"] = peer_value.strip()

        status, response = await self._forward_to_connector(outbound_payload)
        if status >= HTTPStatus.BAD_REQUEST:
            return status, response
        return HTTPStatus.ACCEPTED, {"status": "accepted"}

    async def _forward_to_connector(self, payload: dict[str, str]) -> tuple[int, dict[str, Any]]:
        connector_url = str(self.config.connector_url or "").strip()
        if not connector_url:
            return HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "connector_url is not configured"}

        timeout_s = float(self.config.connector_timeout_seconds or 10.0)
        timeout_s = max(0.1, timeout_s)

        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(connector_url, json=payload)
        except httpx.HTTPError as e:
            logger.error("Webhook connector forward failed: {}", e)
            return HTTPStatus.BAD_GATEWAY, {"error": "Failed to reach connector endpoint"}

        if response.status_code // 100 != 2:
            logger.warning(
                "Webhook connector rejected outbound message: status={} body={}",
                response.status_code,
                response.text[:300],
            )
            return HTTPStatus.BAD_GATEWAY, {"error": "Connector rejected outbound message"}

        return HTTPStatus.ACCEPTED, {"status": "accepted"}

    @staticmethod
    def _normalize_path(value: str, default: str) -> str:
        path = (value or "").strip() or default
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    @staticmethod
    def _header(headers: Mapping[str, Any], name: str) -> str:
        lookup = name.lower()
        for key, value in headers.items():
            if str(key).lower() == lookup and value is not None:
                return str(value).strip()
        return ""

    def _is_json_content_type(self, headers: Mapping[str, Any]) -> bool:
        content_type = self._header(headers, "Content-Type").lower()
        media_type = content_type.split(";", 1)[0].strip()
        return media_type == "application/json"

    def _is_authorized(self, headers: Mapping[str, Any]) -> bool:
        expected = str(self.config.token or "")
        if not expected:
            return True
        return self._resolve_auth_token(headers) == expected

    def _resolve_auth_token(self, headers: Mapping[str, Any]) -> str:
        token = self._header(headers, "x-webhook-token")
        if token:
            return token

        authorization = self._header(headers, "Authorization")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return authorization

    @staticmethod
    def _decode_json_body(body: bytes) -> Any | None:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _resolve_sender_id(self, headers: Mapping[str, Any], remote_addr: str) -> str:
        for key in ("x-webhook-sender-id", "x-clawdentity-agent-did"):
            value = self._header(headers, key)
            if value:
                return value
        host = remote_addr.strip()
        if host.startswith("[") and "]" in host:
            return host[1 : host.index("]")]
        if ":" in host:
            return host.rsplit(":", 1)[0]
        return host or "webhook"

    def _resolve_chat_id(self, headers: Mapping[str, Any], sender_id: str) -> str:
        for key in ("x-webhook-chat-id", "x-clawdentity-to-agent-did"):
            value = self._header(headers, key)
            if value:
                return value
        return sender_id

    @staticmethod
    def _resolve_payload_content(payload: Any) -> tuple[str, str]:
        payload_json = json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, dict):
            for key in ("content", "text", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value, payload_json
        return payload_json, payload_json

    def _build_handler_class(self) -> type[_WebhookRequestHandler]:
        outer = self

        class Handler(_WebhookRequestHandler):
            channel = outer

        return Handler
