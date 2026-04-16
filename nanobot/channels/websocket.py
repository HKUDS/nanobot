"""WebSocket server channel: nanobot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import email.utils
import hmac
import http
import json
import secrets
import ssl
import time
import uuid
from typing import Any, Self
from urllib.parse import parse_qs, urlparse

from loguru import logger
from pydantic import Field, field_validator, model_validator
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


def _strip_trailing_slash(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path or "/"


def _normalize_config_path(path: str) -> str:
    return _strip_trailing_slash(path)


class WebSocketConfig(Base):
    """WebSocket server channel configuration.

    Clients connect with URLs like ``ws://{host}:{port}{path}?client_id=...&token=...``.
    - ``client_id``: Used for ``allow_from`` authorization; if omitted, a value is generated and logged.
    - ``token``: If non-empty, the ``token`` query param may match this static secret; short-lived tokens
      from ``token_issue_path`` are also accepted.
    - ``token_issue_path``: If non-empty, **GET** (HTTP/1.1) to this path returns JSON
      ``{"token": "...", "expires_in": <seconds>}``; use ``?token=...`` when opening the WebSocket.
      Must differ from ``path`` (the WS upgrade path). If the client runs in the **same process** as
      nanobot and shares the asyncio loop, use a thread or async HTTP client for GET—do not call
      blocking ``urllib`` or synchronous ``httpx`` from inside a coroutine.
    - ``token_issue_secret``: If non-empty, token requests must send ``Authorization: Bearer <secret>`` or
      ``X-Nanobot-Auth: <secret>``.
    - ``websocket_requires_token``: If True, the handshake must include a valid token (static or issued and not expired).
    - Each connection has its own session: a unique ``chat_id`` maps to the agent session internally.
      Clients may pass ``chat_id`` (UUID) on the query string to resume a persisted session; see
      ``resume_chat_id``.
    - ``resume_chat_id``: If True (default), optional query ``chat_id=<uuid>`` selects that session;
      if False, the parameter is ignored and a new UUID is always assigned.
    - ``media`` field in outbound messages contains local filesystem paths; remote clients need a
      shared filesystem or an HTTP file server to access these files.
    - Tool rounds can emit JSON frames with ``event: "tool_event"`` (``tool_calls`` before execution,
      ``tool_results`` after). This is gated by global config ``channels.sendToolEvents`` / ``send_tool_events``
      (default off).
    - Each agent turn emits ``event: "chat_start"`` before processing and ``event: "chat_end"`` after
      the turn completes (including after errors), so clients can show typing or progress UI.
    - Assistant ``reasoning_content`` from the persisted turn is sent as ``event: "reasoning"`` after
      streaming completes when applicable, or on ``event: "message"`` as field ``reasoning_content``,
      when global ``channels.sendReasoningContent`` / ``send_reasoning_content`` is true (default).
      The same global flag controls whether other channels receive reasoning on outbound messages.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/"
    token: str = ""
    token_issue_path: str = ""
    token_issue_secret: str = ""
    token_ttl_s: int = Field(default=300, ge=30, le=86_400)
    websocket_requires_token: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    max_message_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    ping_interval_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ping_timeout_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    resume_chat_id: bool = True

    @field_validator("path")
    @classmethod
    def path_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError('path must start with "/"')
        return _normalize_config_path(value)

    @field_validator("token_issue_path")
    @classmethod
    def token_issue_path_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError('token_issue_path must start with "/"')
        return _normalize_config_path(value)

    @model_validator(mode="after")
    def token_issue_path_differs_from_ws_path(self) -> Self:
        if not self.token_issue_path:
            return self
        if _normalize_config_path(self.token_issue_path) == _normalize_config_path(self.path):
            raise ValueError("token_issue_path must differ from path (the WebSocket upgrade path)")
        return self


def _http_json_response(data: dict[str, Any], *, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", "application/json; charset=utf-8"),
        ]
    )
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, headers, body)


def _parse_request_path(path_with_query: str) -> tuple[str, dict[str, list[str]]]:
    """Parse normalized path and query parameters in one pass."""
    parsed = urlparse("ws://x" + path_with_query)
    path = _strip_trailing_slash(parsed.path or "/")
    return path, parse_qs(parsed.query)


def _normalize_http_path(path_with_query: str) -> str:
    """Return the path component (no query string), with trailing slash normalized (root stays ``/``)."""
    return _parse_request_path(path_with_query)[0]


def _parse_query(path_with_query: str) -> dict[str, list[str]]:
    return _parse_request_path(path_with_query)[1]


def _query_first(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key*, or None."""
    values = query.get(key)
    return values[0] if values else None


def _parse_resume_chat_id(raw: str | None) -> str | None:
    """Return canonical UUID string for *raw*, or None if absent or blank.

    Raises ValueError if *raw* is non-blank but not a valid UUID.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    return str(uuid.UUID(s))


def _parse_inbound_payload(raw: str) -> str | None:
    """Parse a client frame into text; return None for empty or unrecognized content."""
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("content", "text", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return None
        return None
    return text


def _issue_route_secret_matches(headers: Any, configured_secret: str) -> bool:
    """Return True if the token-issue HTTP request carries credentials matching ``token_issue_secret``."""
    if not configured_secret:
        return True
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        return hmac.compare_digest(supplied, configured_secret)
    header_token = headers.get("X-Nanobot-Auth") or headers.get("x-nanobot-auth")
    if not header_token:
        return False
    return hmac.compare_digest(header_token.strip(), configured_secret)


class WebSocketChannel(BaseChannel):
    """Run a local WebSocket server; forward text/JSON messages to the message bus."""

    name = "websocket"
    display_name = "WebSocket"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebSocketConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebSocketConfig = config
        self._connections: dict[str, Any] = {}
        self._issued_tokens: dict[str, float] = {}
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebSocketConfig().model_dump(by_alias=True)

    def _expected_path(self) -> str:
        return _normalize_config_path(self.config.path)

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        cert = self.config.ssl_certfile.strip()
        key = self.config.ssl_keyfile.strip()
        if not cert and not key:
            return None
        if not cert or not key:
            raise ValueError(
                "websocket: ssl_certfile and ssl_keyfile must both be set for WSS, or both left empty"
            )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    _MAX_ISSUED_TOKENS = 10_000

    def _purge_expired_issued_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._issued_tokens.items()):
            if now > expiry:
                self._issued_tokens.pop(token_key, None)

    def _take_issued_token_if_valid(self, token_value: str | None) -> bool:
        """Validate and consume one issued token (single use per connection attempt).

        Uses single-step pop to minimize the window between lookup and removal;
        safe under asyncio's single-threaded cooperative model.
        """
        if not token_value:
            return False
        self._purge_expired_issued_tokens()
        expiry = self._issued_tokens.pop(token_value, None)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            return False
        return True

    def _handle_token_issue_http(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            logger.warning(
                "websocket: token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        self._purge_expired_issued_tokens()
        if len(self._issued_tokens) >= self._MAX_ISSUED_TOKENS:
            logger.error(
                "websocket: too many outstanding issued tokens ({}), rejecting issuance",
                len(self._issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = f"nbwt_{secrets.token_urlsafe(32)}"
        self._issued_tokens[token_value] = time.monotonic() + float(self.config.token_ttl_s)

        return _http_json_response(
            {"token": token_value, "expires_in": self.config.token_ttl_s}
        )

    def _authorize_websocket_handshake(self, connection: Any, query: dict[str, list[str]]) -> Any:
        supplied = _query_first(query, "token")
        static_token = self.config.token.strip()

        if static_token:
            if supplied and hmac.compare_digest(supplied, static_token):
                return None
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if self.config.websocket_requires_token:
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if supplied:
            self._take_issued_token_if_valid(supplied)
        return None

    async def start(self) -> None:
        self._running = True
        self._stop_event = asyncio.Event()

        ssl_context = self._build_ssl_context()
        scheme = "wss" if ssl_context else "ws"

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            got, _ = _parse_request_path(request.path)
            if self.config.token_issue_path:
                issue_expected = _normalize_config_path(self.config.token_issue_path)
                if got == issue_expected:
                    return self._handle_token_issue_http(connection, request)

            expected_ws = self._expected_path()
            if got != expected_ws:
                return connection.respond(404, "Not Found")
            # Early reject before WebSocket upgrade to avoid unnecessary overhead;
            # _handle_message() performs a second check as defense-in-depth.
            query = _parse_query(request.path)
            client_id = _query_first(query, "client_id") or ""
            if len(client_id) > 128:
                client_id = client_id[:128]
            if not self.is_allowed(client_id):
                return connection.respond(403, "Forbidden")
            if self.config.resume_chat_id:
                raw_chat = _query_first(query, "chat_id")
                if raw_chat is not None and raw_chat.strip():
                    try:
                        _parse_resume_chat_id(raw_chat)
                    except ValueError:
                        return connection.respond(400, "Bad Request")
            return self._authorize_websocket_handshake(connection, query)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        logger.info(
            "WebSocket server listening on {}://{}:{}{}",
            scheme,
            self.config.host,
            self.config.port,
            self.config.path,
        )
        if self.config.token_issue_path:
            logger.info(
                "WebSocket token issue route: {}://{}:{}{}",
                scheme,
                self.config.host,
                self.config.port,
                _normalize_config_path(self.config.token_issue_path),
            )

        async def runner() -> None:
            async with serve(
                handler,
                self.config.host,
                self.config.port,
                process_request=process_request,
                max_size=self.config.max_message_bytes,
                ping_interval=self.config.ping_interval_s,
                ping_timeout=self.config.ping_timeout_s,
                ssl=ssl_context,
            ):
                assert self._stop_event is not None
                await self._stop_event.wait()

        self._server_task = asyncio.create_task(runner())
        await self._server_task

    async def _connection_loop(self, connection: Any) -> None:
        request = connection.request
        path_part = request.path if request else "/"
        _, query = _parse_request_path(path_part)
        client_id_raw = _query_first(query, "client_id")
        client_id = client_id_raw.strip() if client_id_raw else ""
        if not client_id:
            client_id = f"anon-{uuid.uuid4().hex[:12]}"
        elif len(client_id) > 128:
            logger.warning("websocket: client_id too long ({} chars), truncating", len(client_id))
            client_id = client_id[:128]

        resumed = False
        old_connection: Any | None = None
        if self.config.resume_chat_id:
            maybe_resume = _parse_resume_chat_id(_query_first(query, "chat_id"))
            if maybe_resume is not None:
                chat_id = maybe_resume
                resumed = True
                old_connection = self._connections.get(chat_id)
            else:
                chat_id = str(uuid.uuid4())
        else:
            chat_id = str(uuid.uuid4())

        ready_body: dict[str, Any] = {
            "event": "ready",
            "chat_id": chat_id,
            "client_id": client_id,
        }
        if resumed:
            ready_body["resumed"] = True

        try:
            await connection.send(json.dumps(ready_body, ensure_ascii=False))
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._connections[chat_id] = connection
            if old_connection is not None and old_connection is not connection:
                try:
                    await old_connection.close(1000, "replaced by new connection")
                except Exception as e:
                    logger.debug("websocket: closing replaced connection: {}", e)

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning("websocket: ignoring non-utf8 binary frame")
                        continue
                content = _parse_inbound_payload(raw)
                if content is None:
                    continue
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=chat_id,
                    content=content,
                    metadata={"remote": getattr(connection, "remote_address", None)},
                )
        except Exception as e:
            logger.debug("websocket connection ended: {}", e)
        finally:
            if self._connections.get(chat_id) is connection:
                self._connections.pop(chat_id, None)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except Exception as e:
                logger.warning("websocket: server task error during shutdown: {}", e)
            self._server_task = None
        self._connections.clear()
        self._issued_tokens.clear()

    async def _safe_send(self, chat_id: str, raw: str, *, label: str = "") -> None:
        """Send a raw frame, cleaning up dead connections on ConnectionClosed."""
        connection = self._connections.get(chat_id)
        if connection is None:
            return
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._connections.pop(chat_id, None)
            logger.warning("websocket{}connection gone for chat_id={}", label, chat_id)
        except Exception as e:
            logger.error("websocket{}send failed: {}", label, e)
            raise

    async def send(self, msg: OutboundMessage) -> None:
        connection = self._connections.get(msg.chat_id)
        if connection is None:
            logger.warning("websocket: no active connection for chat_id={}", msg.chat_id)
            return
        metadata = msg.metadata or {}
        if metadata.get("_reasoning_only"):
            rc = metadata.get("reasoning_content")
            if isinstance(rc, str) and rc:
                payload = {"event": "reasoning", "text": rc}
                await self._safe_send(
                    msg.chat_id, json.dumps(payload, ensure_ascii=False), label=" reasoning "
                )
            return
        turn_phase = metadata.get("_session_turn_event")
        if turn_phase in ("start", "end"):
            payload = {
                "event": "chat_start" if turn_phase == "start" else "chat_end",
            }
            await self._safe_send(
                msg.chat_id, json.dumps(payload, ensure_ascii=False), label=" turn "
            )
            return
        if metadata.get("_tool_event"):
            payload = {"event": "tool_event"}
            for key in ("tool_calls", "tool_results"):
                if key in metadata:
                    payload[key] = metadata[key]
        else:
            payload = {"event": "message", "text": msg.content}
            if msg.media:
                payload["media"] = msg.media
            if msg.reply_to:
                payload["reply_to"] = msg.reply_to
            if msg.data:
                payload["data"] = msg.data
            rc = metadata.get("reasoning_content")
            if isinstance(rc, str) and rc:
                payload["reasoning_content"] = rc
        await self._safe_send(msg.chat_id, json.dumps(payload, ensure_ascii=False), label=" ")

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._connections.get(chat_id) is None:
            return
        meta = metadata or {}
        if meta.get("_stream_end"):
            body: dict[str, Any] = {"event": "stream_end"}
        else:
            body = {
                "event": "delta",
                "text": delta,
            }
        if meta.get("_stream_id") is not None:
            body["stream_id"] = meta["_stream_id"]
        raw = json.dumps(body, ensure_ascii=False)
        await self._safe_send(chat_id, raw, label=" stream ")
