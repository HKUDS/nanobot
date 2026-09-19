"""Shared local HTTP listener for Linear webhooks and OAuth callbacks."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from loguru import logger

from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.oauth import OAUTH_FLOWS
from nanobot.channels.linear.state import LinearStateStore

MAX_WEBHOOK_BYTES = 1024 * 1024
MAX_WEBHOOK_AGE_SECONDS = 60
WEBHOOK_TYPES = {
    "AgentSessionEvent",
    "OAuthApp",
    "OAuthAuthorization",
    "PermissionChange",
}


class LinearWebhookError(ValueError):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class SharedLinearHttpServer:
    def __init__(self, config: LinearConfig, state: LinearStateStore) -> None:
        self.config = config
        self.state = state
        self._references = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def identity(self) -> tuple[str, int, str, str, str, str]:
        return (
            self.config.host,
            self.config.port,
            self.config.client_id,
            self.config.webhook_signing_secret,
            self.config.webhook_path,
            self.config.oauth_callback_path,
        )

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == owner.config.oauth_callback_path:
                    owner._handle_oauth_callback(self, parse_qs(parsed.query))
                    return
                if parsed.path == "/linear/health":
                    self._send(HTTPStatus.OK, b'{"ok":true}', "application/json")
                    return
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != owner.config.webhook_path:
                    self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                    return
                try:
                    owner._handle_webhook(self)
                except LinearWebhookError as exc:
                    logger.bind(channel="linear").warning("Rejected Linear webhook: {}", exc)
                    self._send(exc.status, str(exc).encode(), "text/plain; charset=utf-8")
                except Exception:
                    logger.bind(channel="linear").exception(
                        "Could not persist a verified Linear webhook"
                    )
                    self._send(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        b"webhook persistence failed",
                        "text/plain; charset=utf-8",
                    )

            def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
                self.send_response(status.value)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = _ReusableThreadingHTTPServer(
            (self.config.host, self.config.port),
            Handler,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="nanobot-linear",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _handle_oauth_callback(
        self,
        handler: BaseHTTPRequestHandler,
        query: dict[str, list[str]],
    ) -> None:
        state = _query_first(query, "state")
        code = _query_first(query, "code")
        error = _query_first(query, "error")
        if not state or (not code and not error):
            _handler_response(handler, HTTPStatus.BAD_REQUEST, _oauth_html(False))
            return
        completed = OAUTH_FLOWS.complete(state, code=code, error=error)
        _handler_response(
            handler,
            HTTPStatus.OK if completed else HTTPStatus.BAD_REQUEST,
            _oauth_html(completed),
        )

    def _handle_webhook(self, handler: BaseHTTPRequestHandler) -> None:
        raw_length = handler.headers.get("Content-Length")
        try:
            length = int(raw_length or "")
        except ValueError as exc:
            raise LinearWebhookError("invalid content length") from exc
        if length <= 0 or length > MAX_WEBHOOK_BYTES:
            raise LinearWebhookError("invalid content length", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = handler.rfile.read(length)
        signature = handler.headers.get("Linear-Signature", "").strip()
        expected = hmac.new(
            self.config.webhook_signing_secret.encode(),
            raw,
            hashlib.sha256,
        ).hexdigest()
        if not signature or not hmac.compare_digest(signature.lower(), expected):
            raise LinearWebhookError("invalid signature", HTTPStatus.UNAUTHORIZED)
        delivery_id = handler.headers.get("Linear-Delivery", "").strip()
        if not delivery_id or len(delivery_id) > 200:
            raise LinearWebhookError("missing delivery id")
        try:
            value: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LinearWebhookError("invalid JSON") from exc
        if not isinstance(value, dict):
            raise LinearWebhookError("webhook body must be an object")
        payload = cast(dict[str, Any], value)
        timestamp = _webhook_timestamp(payload.get("webhookTimestamp"))
        if timestamp is None or abs(time.time() - timestamp) > MAX_WEBHOOK_AGE_SECONDS:
            raise LinearWebhookError("stale webhook", HTTPStatus.UNAUTHORIZED)
        event_type = payload.get("type")
        if event_type not in WEBHOOK_TYPES:
            _handler_response(handler, HTTPStatus.OK, b'{"ok":true,"ignored":true}', "application/json")
            return
        oauth_client_id = payload.get("oauthClientId")
        if oauth_client_id != self.config.client_id:
            raise LinearWebhookError("webhook belongs to another OAuth app", HTTPStatus.FORBIDDEN)
        self.state.enqueue_webhook(delivery_id, payload)
        _handler_response(handler, HTTPStatus.OK, b'{"ok":true}', "application/json")


class LinearServerLease:
    def __init__(self, server: SharedLinearHttpServer) -> None:
        self._server = server
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _release_server(self._server)


_SERVER_GUARD = threading.RLock()
_shared_server: SharedLinearHttpServer | None = None


def acquire_http_server(config: LinearConfig, state: LinearStateStore) -> LinearServerLease:
    global _shared_server
    with _SERVER_GUARD:
        candidate = SharedLinearHttpServer(config, state)
        if _shared_server is None:
            candidate.start()
            _shared_server = candidate
        elif _shared_server.identity != candidate.identity:
            raise RuntimeError(
                "A Linear callback listener is already running with different settings"
            )
        _shared_server._references += 1  # pyright: ignore[reportPrivateUsage]
        return LinearServerLease(_shared_server)


def _release_server(server: SharedLinearHttpServer) -> None:
    global _shared_server
    with _SERVER_GUARD:
        if _shared_server is not server:
            return
        server._references -= 1  # pyright: ignore[reportPrivateUsage]
        if server._references <= 0:  # pyright: ignore[reportPrivateUsage]
            server.close()
            _shared_server = None


def _handler_response(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    body: bytes,
    content_type: str = "text/html; charset=utf-8",
) -> None:
    handler.send_response(status.value)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _oauth_html(success: bool) -> bytes:
    title = "Linear connected" if success else "Linear connection failed"
    detail = (
        "Authorization received. You can close this window and return to nanobot."
        if success
        else "The authorization request is invalid or expired. Return to nanobot and try again."
    )
    return (
        "<!doctype html><html><head><meta charset=utf-8><title>"
        + title
        + "</title></head><body><main><h1>"
        + title
        + "</h1><p>"
        + detail
        + "</p></main></body></html>"
    ).encode()


def _query_first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values and values[0] else None


def _webhook_timestamp(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        timestamp = float(value)
        return timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = float(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
