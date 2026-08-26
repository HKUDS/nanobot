"""WebSocket server channel: nanobot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import ssl
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, TypeGuard, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, PrivateAttr, field_validator, model_validator
from websockets.asyncio.server import Server, ServerConnection, serve, unix_serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest

from nanobot.bus.events import (
    OUTBOUND_META_AGENT_UI,
    OutboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.session.webui_turns import (
    clear_websocket_turn_if_current,
    mark_websocket_turn_transcript_persistence_failed,
    websocket_turn_transcript_persistence_failed,
)
from nanobot.webui.gateway_services import GatewayServices
from nanobot.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from nanobot.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from nanobot.webui.http_utils import (
    query_first as _query_first,
)
from nanobot.webui.inbound_commands import WebUICommandRouter
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)
from nanobot.webui.outbound_projection import WebUIOutboundProjector
from nanobot.webui.session_identity import is_valid_webui_chat_id
from nanobot.webui.transcript import WEBUI_TRANSCRIPT_INCOMPLETE_KEY
from nanobot.webui.websocket_logging import websockets_server_logger

if TYPE_CHECKING:
    from nanobot.bus.outbound_events import ProgressEvent, RecoveryStateEvent
    from nanobot.providers.base import LLMUsage

# Plain HTTP WebUI routes also run through websockets.process_request.
_WEBUI_HTTP_OPEN_TIMEOUT_S = 360.0
_LISTENER_CHECK_INTERVAL_S = 0.5
_LISTENER_STABLE_AFTER_S = 30.0
_LISTENER_RESTART_BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

# A bind conflict or invalid address needs operator action and must not be
# retried forever. These errors can be caused by a transient local network
# interruption and are safe to retry at the channel boundary.
_RECOVERABLE_LISTENER_ERRNOS = {
    getattr(socket, name)
    for name in (
        "ECONNABORTED",
        "ECONNRESET",
        "EHOSTDOWN",
        "EHOSTUNREACH",
        "ENETDOWN",
        "ENETRESET",
        "ENETUNREACH",
        "ETIMEDOUT",
    )
    if hasattr(socket, name)
}
_RECOVERABLE_LISTENER_WINERRORS = {
    64,  # ERROR_NETNAME_DELETED / "The specified network name is no longer available."
    995,  # ERROR_OPERATION_ABORTED
    10050,  # WSAENETDOWN
    10052,  # WSAENETRESET
    10053,  # WSAECONNABORTED
    10054,  # WSAECONNRESET
    10060,  # WSAETIMEDOUT
    10065,  # WSAEHOSTUNREACH
}


_ROUTING_ASSERTION_HEADERS = frozenset(
    {
        "host",
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-real-ip",
        "cf-connecting-ip",
    }
)


def _is_routing_assertion_header(value: str) -> bool:
    normalized = value.casefold()
    return normalized in _ROUTING_ASSERTION_HEADERS or normalized.startswith("x-forwarded-")


class TrustedProxyAuthConfig(Base):
    """Authentication assertions accepted from explicitly trusted proxy peers."""

    trusted_peer_cidrs: list[str] = Field(min_length=1)
    assertion_header: str = Field(min_length=1)
    _trusted_peer_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = PrivateAttr(
        default=()
    )

    @field_validator("trusted_peer_cidrs")
    @classmethod
    def validate_trusted_peer_cidrs(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            value = value.strip()
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid trusted proxy CIDR: {value!r}") from exc
            if network.prefixlen == 0:
                raise ValueError("universal trusted proxy CIDRs are not allowed")
            if isinstance(network, ipaddress.IPv6Network):
                mapped_start = ipaddress.IPv6Address("::ffff:0:0")
                mapped_end = ipaddress.IPv6Address("::ffff:ffff:ffff")
                if mapped_start in network and mapped_end in network:
                    raise ValueError("trusted proxy CIDRs must not cover all IPv4-mapped addresses")
            normalized.append(network.with_prefixlen)
        return normalized

    @field_validator("assertion_header")
    @classmethod
    def validate_assertion_header(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() or ord(char) < 0x21 for char in value):
            raise ValueError("assertion_header must be a valid HTTP header name")
        if _is_routing_assertion_header(value):
            raise ValueError(
                "assertion_header must identify a proxy-generated authentication assertion, "
                "not a routing or client metadata header"
            )
        return value

    @model_validator(mode="after")
    def compile_trusted_peer_networks(self) -> Self:
        self._trusted_peer_networks = tuple(
            ipaddress.ip_network(value, strict=False) for value in self.trusted_peer_cidrs
        )
        return self


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
    - ``public_ws_url``: Optional public WebSocket endpoint returned by WebUI bootstrap instead of
      deriving one from proxy request headers. Its path must match ``path``.
    - ``websocket_requires_token``: If True, the handshake must include a valid token (static or issued and not expired).
    - Each connection has its own session: a unique ``chat_id`` maps to the agent session internally.
    - ``media`` field in outbound messages contains local filesystem paths; remote clients need a
      shared filesystem or an HTTP file server to access these files.
    """

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    unix_socket_path: str = ""
    path: str = "/"
    public_ws_url: str = ""
    token: str = ""
    token_issue_path: str = ""
    token_issue_secret: str = ""
    trusted_proxy_auth: TrustedProxyAuthConfig | None = None
    token_ttl_s: int = Field(default=300, ge=30, le=86_400)
    websocket_requires_token: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    # Default 36 MB, upper 40 MB: supports up to 4 images at ~6 MB each after
    # client-side Worker normalization (see webui Composer). 4 × 6 MB × 1.37
    # (base64 overhead) + envelope framing stays under 36 MB; the 40 MB ceiling
    # leaves a small margin for sender slop without opening a DoS avenue.
    max_message_bytes: int = Field(default=37_748_736, ge=1024, le=41_943_040)
    ping_interval_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ping_timeout_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    @field_validator("unix_socket_path")
    @classmethod
    def unix_socket_path_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if "\x00" in value:
            raise ValueError("unix_socket_path must not contain NUL bytes")
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("unix_socket_path must be an absolute path")
        return str(path)

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

    @field_validator("public_ws_url")
    @classmethod
    def public_ws_url_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"ws", "wss"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public_ws_url must be an absolute ws:// or wss:// URL without credentials")
        return urlunsplit(
            (parsed.scheme, parsed.netloc, _normalize_config_path(parsed.path or "/"), "", "")
        )

    @model_validator(mode="after")
    def public_ws_url_matches_path(self) -> Self:
        if self.public_ws_url and urlsplit(self.public_ws_url).path != _normalize_config_path(self.path):
            raise ValueError("public_ws_url path must match path")
        return self

    @model_validator(mode="after")
    def token_issue_path_differs_from_ws_path(self) -> Self:
        if not self.token_issue_path:
            return self
        if _normalize_config_path(self.token_issue_path) == _normalize_config_path(self.path):
            raise ValueError("token_issue_path must differ from path (the WebSocket upgrade path)")
        return self

    @model_validator(mode="after")
    def wildcard_host_requires_auth(self) -> Self:
        if self.host not in ("0.0.0.0", "::"):
            return self
        if self.token.strip() or self.token_issue_secret.strip() or self.trusted_proxy_auth is not None:
            return self
        raise ValueError(
            "host is 0.0.0.0 (all interfaces) but neither token, token_issue_secret, "
            "nor trusted_proxy_auth is set — set one to prevent unauthenticated access"
        )


def _parse_inbound_payload(raw: str) -> str | None:
    """Parse a client frame into text; return None for empty or unrecognized content."""
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = cast(object, json.loads(text))
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            payload = cast(dict[str, Any], data)
            for key in ("content", "text", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return None
        return None
    return text


def _is_valid_chat_id(value: Any) -> TypeGuard[str]:  # pyright: ignore[reportUnusedFunction]
    return is_valid_webui_chat_id(value)


def _parse_envelope(raw: str) -> dict[str, Any] | None:
    """Return a typed envelope dict if the frame is a new-style JSON envelope, else None.

    A frame qualifies when it parses as a JSON object with a string ``type`` field.
    Legacy frames (plain text, or ``{"content": ...}`` without ``type``) return None;
    callers should fall back to :func:`_parse_inbound_payload` for those.
    """
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        data = cast(object, json.loads(text))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    envelope = cast(dict[str, Any], data)
    t = envelope.get("type")
    if not isinstance(t, str):
        return None
    return envelope


class _ListenerUnavailableError(OSError):
    """Raised when a previously bound listener loses its serving socket."""


class WebSocketChannel(BaseChannel):
    """Run a local WebSocket server; forward text/JSON messages to the message bus."""

    name = "websocket"
    display_name = "WebSocket"

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        *,
        gateway: GatewayServices,
    ):
        if isinstance(config, dict):
            config = WebSocketConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebSocketConfig = config
        # chat_id -> connections subscribed to it (fan-out target).
        self._subs: dict[str, set[ServerConnection]] = {}
        # connection -> chat_ids it is subscribed to (O(1) cleanup on disconnect).
        self._conn_chats: dict[ServerConnection, set[str]] = {}
        # connection -> default chat_id for legacy frames that omit routing.
        self._conn_default: dict[ServerConnection, str] = {}
        # Connections authenticated with a one-time token from /webui/bootstrap.
        self._webui_connections = gateway.endpoint.webui_connections
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._server: Server | None = None

        self.gateway = gateway
        self._media = gateway.media
        self._transcripts = gateway.transcripts
        self._temporary_chats = gateway.temporary_chats
        self._session_projection = gateway.session_projection
        self._commands = WebUICommandRouter(self, gateway)
        self._webui_request_tasks = self._commands.request_tasks
        self._webui_request_operations = self._commands.request_operations
        self._webui_request_locks = self._commands.request_locks
        self._outbound = WebUIOutboundProjector(self, self._session_projection)

        self._stream_text_buffers: dict[tuple[str, str], list[str]] = {}
        self._reasoning_text_buffers: dict[tuple[str, str], list[str]] = {}

    # -- Subscription bookkeeping -------------------------------------------

    def webui_subscribers(self, chat_id: str) -> tuple[ServerConnection, ...]:
        """Return a stable snapshot of one chat's transport subscribers."""
        return tuple(self._subs.get(chat_id, ()))

    def webui_connection_chats(self, connection: ServerConnection) -> tuple[str, ...]:
        return tuple(self._conn_chats.get(connection, ()))

    def webui_attach(self, connection: ServerConnection, chat_id: str) -> None:
        self._attach(connection, chat_id)

    def webui_detach(self, connection: ServerConnection, chat_id: str) -> None:
        self._detach(connection, chat_id)

    def webui_clear_connection_default(self, connection: ServerConnection) -> None:
        self._conn_default.pop(connection, None)

    def webui_clear_stream_buffers(self, chat_id: str) -> None:
        self._clear_stream_buffers(chat_id)

    async def webui_hydrate(self, chat_id: str) -> None:
        await self._hydrate_after_subscribe(chat_id)

    async def webui_send_event(
        self,
        connection: ServerConnection,
        event: str,
        **fields: Any,
    ) -> None:
        await self._send_event(connection, event, **fields)

    async def webui_send_raw(
        self,
        connection: ServerConnection,
        raw: str,
        *,
        label: str = "",
    ) -> None:
        await self._safe_send_to(connection, raw, label=label)

    async def webui_dispatch_message(
        self,
        *,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None,
        metadata: dict[str, Any],
        is_dm: bool,
        session_key: str | None,
        require_existing_session: bool,
    ) -> None:
        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media,
            metadata=metadata,
            is_dm=is_dm,
            session_key=session_key,
            require_existing_session=require_existing_session,
        )

    def _attach(self, connection: ServerConnection, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _detach(self, connection: ServerConnection, chat_id: str) -> None:
        chats = self._conn_chats.get(connection)
        if chats is not None:
            chats.discard(chat_id)
            if not chats:
                self._conn_chats.pop(connection, None)
        subscribers = self._subs.get(chat_id)
        if subscribers is not None:
            subscribers.discard(connection)
            if not subscribers:
                self._subs.pop(chat_id, None)

    def _clear_stream_buffers(self, chat_id: str) -> None:
        for key in tuple(self._stream_text_buffers):
            if key[0] == chat_id:
                self._stream_text_buffers.pop(key, None)
        for key in tuple(self._reasoning_text_buffers):
            if key[0] == chat_id:
                self._reasoning_text_buffers.pop(key, None)

    async def _cleanup_connection(self, connection: ServerConnection) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        await self._commands.cleanup_connection(connection)

    async def _hydrate_after_subscribe(self, chat_id: str) -> None:
        """Replay persisted or actively running per-chat state after subscribe."""
        await self._outbound.hydrate(chat_id)

    async def _send_event(
        self,
        connection: ServerConnection,
        event: str,
        **fields: Any,
    ) -> None:
        """Send a control event (attached, error, ...) to a single connection."""
        payload: dict[str, Any] = {"event": event}
        payload.update(fields)
        raw = json.dumps(payload, ensure_ascii=False)
        try:
            await connection.send(raw)
        except ConnectionClosed:
            await self._cleanup_connection(connection)
        except Exception as e:
            self.logger.warning("failed to send {} event: {}", event, e)

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
                "ssl_certfile and ssl_keyfile must both be set for WSS, or both left empty"
            )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    # -- HTTP dispatch ------------------------------------------------------

    async def _dispatch_http(self, connection: ServerConnection, request: WsRequest) -> Any:
        """Compatibility proxy for the externally composed gateway endpoint."""
        return await self.gateway.endpoint.process_request(
            connection,
            request,
            is_allowed=self.is_allowed,
        )

    def _authorize_websocket_handshake(
        self,
        connection: ServerConnection,
        query: dict[str, list[str]],
        headers: Any = None,
    ) -> Any:
        """Compatibility proxy for handshake tests and integrations."""
        return self.gateway.endpoint.authorize_websocket_handshake(
            connection,
            query,
            headers,
        )

    def _consume_issued_token(self, connection: ServerConnection, token: str) -> bool:
        return self.gateway.endpoint.consume_issued_token(connection, token)

    # -- Server lifecycle and connection ingress ---------------------------

    @staticmethod
    def _listener_is_serving(server: Server) -> bool:
        """Return whether every bound socket still has a live listen capability."""
        try:
            sockets = server.sockets
            return bool(sockets) and server.is_serving() and all(
                sock.fileno() >= 0
                and bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
                for sock in sockets
            )
        except OSError:
            return False

    @staticmethod
    def _is_recoverable_listener_error(error: Exception, *, was_serving: bool) -> bool:
        if isinstance(error, _ListenerUnavailableError):
            return True
        if not isinstance(error, OSError):
            return False
        if was_serving:
            return True
        winerror = getattr(error, "winerror", None)
        return (
            error.errno in _RECOVERABLE_LISTENER_ERRNOS
            or winerror in _RECOVERABLE_LISTENER_WINERRORS
        )

    async def _wait_for_listener_loss(self, server: Server) -> None:
        """Wait for shutdown or raise when the serving socket disappears."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_LISTENER_CHECK_INTERVAL_S,
                )
            except TimeoutError:
                if not self._listener_is_serving(server):
                    raise _ListenerUnavailableError(
                        "WebSocket listener is no longer accepting connections"
                    )

    async def _close_server(self, server: Server, socket_path: str) -> None:
        server.close()
        try:
            await server.wait_closed()
        except OSError as exc:
            self.logger.warning("WebSocket server close failed: {}", exc)
        if socket_path:
            with suppress(FileNotFoundError):
                Path(socket_path).unlink()

    def _log_listener_ready(self, scheme: str) -> None:
        self.logger.info(
            "WebSocket server listening on {}",
            (
                f"unix:{self.config.unix_socket_path}{self.config.path}"
                if self.config.unix_socket_path
                else f"{scheme}://{self.config.host}:{self.config.port}{self.config.path}"
            ),
        )
        if self.config.token_issue_path:
            self.logger.info(
                "WebSocket token issue route: {}",
                (
                    f"unix:{self.config.unix_socket_path}"
                    f"{_normalize_config_path(self.config.token_issue_path)}"
                    if self.config.unix_socket_path
                    else (
                        f"{scheme}://{self.config.host}:{self.config.port}"
                        f"{_normalize_config_path(self.config.token_issue_path)}"
                    )
                ),
            )

    async def start(self) -> None:
        from nanobot.utils.logging_bridge import redirect_lib_logging

        redirect_lib_logging("websockets", level="WARNING")
        ws_logger = websockets_server_logger()

        stop_event = asyncio.Event()
        self._stop_event = stop_event

        ssl_context = self._build_ssl_context()
        scheme = "wss" if ssl_context else "ws"

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            return await self._dispatch_http(connection, request)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        async def runner() -> None:
            socket_path = self.config.unix_socket_path
            failures = 0
            while not stop_event.is_set():
                server: Server | None = None
                was_serving = False
                started_at = 0.0
                try:
                    if socket_path:
                        path_obj = Path(socket_path)
                        path_obj.parent.mkdir(parents=True, exist_ok=True)
                        with suppress(FileNotFoundError):
                            path_obj.unlink()
                        server = await unix_serve(
                            handler,
                            socket_path,
                            process_request=process_request,
                            open_timeout=_WEBUI_HTTP_OPEN_TIMEOUT_S,
                            max_size=self.config.max_message_bytes,
                            ping_interval=self.config.ping_interval_s,
                            ping_timeout=self.config.ping_timeout_s,
                            logger=ws_logger,
                        )
                        with suppress(OSError):
                            path_obj.chmod(0o600)
                    else:
                        server = await serve(
                            handler,
                            self.config.host,
                            self.config.port,
                            process_request=process_request,
                            open_timeout=_WEBUI_HTTP_OPEN_TIMEOUT_S,
                            max_size=self.config.max_message_bytes,
                            ping_interval=self.config.ping_interval_s,
                            ping_timeout=self.config.ping_timeout_s,
                            ssl=ssl_context,
                            logger=ws_logger,
                        )

                    self._server = server
                    was_serving = True
                    if not self._listener_is_serving(server):
                        raise _ListenerUnavailableError(
                            "WebSocket listener did not enter a serving state"
                        )
                    self._running = True
                    started_at = asyncio.get_running_loop().time()
                    self._log_listener_ready(scheme)
                    await self._wait_for_listener_loss(server)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._running = False
                    if not self._is_recoverable_listener_error(
                        exc,
                        was_serving=was_serving,
                    ):
                        raise
                    uptime = (
                        asyncio.get_running_loop().time() - started_at
                        if started_at
                        else 0.0
                    )
                    if uptime >= _LISTENER_STABLE_AFTER_S:
                        failures = 0
                    delay = _LISTENER_RESTART_BACKOFF_S[
                        min(failures, len(_LISTENER_RESTART_BACKOFF_S) - 1)
                    ]
                    failures += 1
                    self.logger.warning(
                        "WebSocket listener failed ({}: {}); retrying in {:.1f}s",
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=delay)
                    except TimeoutError:
                        pass
                finally:
                    self._running = False
                    if server is not None:
                        await self._close_server(server, socket_path)
                    if self._server is server:
                        self._server = None

        task = asyncio.create_task(runner())
        self._server_task = task
        try:
            await task
        finally:
            self._running = False
            if self._server_task is task:
                self._server_task = None

    async def _connection_loop(self, connection: ServerConnection) -> None:
        request = connection.request
        path_part = request.path if request else "/"
        _, query = _parse_request_path(path_part)
        client_id_raw = _query_first(query, "client_id")
        client_id = client_id_raw.strip() if client_id_raw else ""
        if not client_id:
            client_id = f"anon-{uuid.uuid4().hex[:12]}"
        elif len(client_id) > 128:
            self.logger.warning("client_id too long ({} chars), truncating", len(client_id))
            client_id = client_id[:128]

        default_chat_id = str(uuid.uuid4())

        try:
            await connection.send(
                json.dumps(
                    {
                        "event": "ready",
                        "chat_id": default_chat_id,
                        "client_id": client_id,
                    },
                    ensure_ascii=False,
                )
            )
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._conn_default[connection] = default_chat_id
            self._attach(connection, default_chat_id)
            await self._hydrate_after_subscribe(default_chat_id)

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        self.logger.warning("ignoring non-utf8 binary frame")
                        continue

                envelope = _parse_envelope(raw)
                if envelope is not None:
                    await self._dispatch_envelope(connection, client_id, envelope)
                    continue

                content = _parse_inbound_payload(raw)
                if content is None:
                    continue
                # WebSocket already authenticates at handshake time (token),
                # so pairing is not applicable. Treat as non-DM to avoid
                # sending pairing codes to an already-authenticated client.
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=default_chat_id,
                    content=content,
                    metadata={"remote": getattr(connection, "remote_address", None)},
                    is_dm=False,
                )
        except Exception as e:
            self.logger.debug("connection ended: {}", e)
        finally:
            await self._cleanup_connection(connection)

    # -- Inbound WebSocket envelopes ---------------------------------------

    async def _dispatch_envelope(
        self,
        connection: ServerConnection,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        """Delegate one typed envelope to the WebUI application router."""
        await self._commands.dispatch(connection, client_id, envelope)

    def _prune_webui_request_operations(self) -> None:
        """Compatibility hook for request-cache boundary tests."""
        self._commands.prune_request_operations()

    # -- Outbound WebSocket events -----------------------------------------

    async def stop(self) -> None:
        server_task = self._server_task
        if not self._running and server_task is None:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if server_task:
            try:
                await server_task
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
                self.logger.debug("server task was already cancelled during shutdown")
            except Exception as e:
                self.logger.warning("server task error during shutdown: {}", e)
            if self._server_task is server_task:
                self._server_task = None
        await self._commands.close()
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()

    async def _safe_send_to(
        self,
        connection: ServerConnection,
        raw: str,
        *,
        label: str = "",
    ) -> None:
        """Send a raw frame to one connection, cleaning up on ConnectionClosed."""
        try:
            await connection.send(raw)
        except ConnectionClosed:
            await self._cleanup_connection(connection)
            self.logger.warning("connection gone{}", label)
        except Exception:
            self.logger.exception("send failed{}", label)
            raise

    def _persist_turn_transcript_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None,
        phase: str,
        include_source: bool = False,
        transcript_overrides: dict[str, Any] | None = None,
    ) -> bool:
        """Persist one canonical turn event and retain unsafe owners on failure."""
        if not self._temporary_chats.should_persist_transcript(chat_id):
            return True
        persisted = self._transcripts.prepare_and_append(
            chat_id,
            event,
            metadata=metadata,
            phase=phase,
            include_source=include_source,
            transcript_overrides=transcript_overrides,
        )
        return self._retain_turn_on_transcript_failure(
            chat_id,
            persisted=persisted,
            metadata=metadata,
            phase=phase,
        )

    @staticmethod
    def _retain_turn_on_transcript_failure(
        chat_id: str,
        *,
        persisted: bool,
        metadata: dict[str, Any] | None,
        phase: str,
    ) -> bool:
        if not persisted and phase in {"answer", "complete"} and (metadata or {}).get("webui") is True:
            owner = (metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            mark_websocket_turn_transcript_persistence_failed(
                chat_id,
                owner if isinstance(owner, str) else None,
            )
        return persisted

    def _persist_turn_stream_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        completed_text: str | None,
        metadata: dict[str, Any] | None,
        phase: str,
        include_source: bool = False,
    ) -> bool:
        """Persist the canonical end of a live stream, never its wire chunks."""
        if not self._temporary_chats.should_persist_transcript(chat_id):
            return True
        persisted = self._transcripts.prepare_and_append_stream_event(
            chat_id,
            event,
            completed_text=completed_text,
            metadata=metadata,
            phase=phase,
            include_source=include_source,
        )
        return self._retain_turn_on_transcript_failure(
            chat_id,
            persisted=persisted,
            metadata=metadata,
            phase=phase,
        )

    async def send(self, msg: OutboundMessage) -> None:
        await self._outbound.send(msg)

    async def send_projected_message(
        self,
        msg: OutboundMessage,
        progress_event: ProgressEvent | None,
    ) -> None:
        """Serialize one ordinary outbound message selected by the projector."""
        conns = list(self._subs.get(msg.chat_id, ()))
        text = msg.content
        wire_text = self._media.rewrite_local_markdown_images(text)
        payload: dict[str, Any] = {
            "event": "message",
            "chat_id": msg.chat_id,
            "text": wire_text,
        }
        turn_id = msg.metadata.get(WEBUI_TURN_METADATA_KEY)
        if isinstance(turn_id, str) and turn_id:
            payload["turn_id"] = turn_id
        if msg.media:
            payload["media"] = msg.media
            urls: list[dict[str, str]] = []
            for entry in msg.media:
                signed = self._media.sign_or_stage_media_path(Path(entry))
                if signed is not None:
                    urls.append(signed)
            if urls:
                payload["media_urls"] = urls
        if msg.reply_to:
            payload["reply_to"] = msg.reply_to
        lat = msg.metadata.get("latency_ms")
        if isinstance(lat, (int, float)):
            payload["latency_ms"] = int(lat)
        if progress_event and progress_event.tool_events:
            payload["tool_events"] = progress_event.tool_events
        agent_ui = msg.metadata.get(OUTBOUND_META_AGENT_UI)
        if agent_ui is not None:
            payload["agent_ui"] = agent_ui
        # Mark intermediate agent breadcrumbs (tool-call hints, generic
        # progress strings) so WS clients can render them as subordinate
        # trace rows rather than conversational replies.
        if progress_event and progress_event.tool_hint:
            payload["kind"] = "tool_hint"
        elif progress_event:
            payload["kind"] = "progress"
        phase = "activity" if payload.get("kind") in ("tool_hint", "progress") else "answer"
        self._persist_turn_transcript_event(
            msg.chat_id,
            payload,
            metadata=msg.metadata,
            phase=phase,
            include_source=True,
            transcript_overrides={"text": text},
        )
        raw = json.dumps(payload, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" ")

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        """Push one chunk of model reasoning. Mirrors ``send_delta`` shape so
        clients receive a stream that opens, updates in place, and closes —
        rendered above the active assistant bubble with a shimmer header
        until the matching ``reasoning_end`` arrives.
        """
        conns = list(self._subs.get(chat_id, ()))
        if not delta:
            return
        meta = metadata or {}
        body: dict[str, Any] = {
            "event": "reasoning_delta",
            "chat_id": chat_id,
            "text": delta,
        }
        if stream_id is not None:
            body["stream_id"] = stream_id
        stream_key = (chat_id, str(stream_id or ""))
        self._reasoning_text_buffers.setdefault(stream_key, []).append(delta)
        self._persist_turn_stream_event(
            chat_id,
            body,
            completed_text=None,
            metadata=meta,
            phase="reasoning",
        )
        raw = json.dumps(body, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" reasoning ")

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        """Close the current reasoning stream segment for in-place renderers."""
        conns = list(self._subs.get(chat_id, ()))
        meta = metadata or {}
        body: dict[str, Any] = {
            "event": "reasoning_end",
            "chat_id": chat_id,
        }
        if stream_id is not None:
            body["stream_id"] = stream_id
        stream_key = (chat_id, str(stream_id or ""))
        reasoning_text = "".join(self._reasoning_text_buffers.pop(stream_key, []))
        self._persist_turn_stream_event(
            chat_id,
            body,
            completed_text=reasoning_text or None,
            metadata=meta,
            phase="reasoning",
        )
        raw = json.dumps(body, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" reasoning_end ")

    async def send_file_edit_events(
        self,
        chat_id: str,
        edits: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conns = list(self._subs.get(chat_id, ()))
        payload: dict[str, Any] = {
            "event": "file_edit",
            "chat_id": chat_id,
            "edits": edits,
        }
        self._persist_turn_transcript_event(
            chat_id,
            payload,
            metadata=metadata,
            phase="activity",
        )
        raw = json.dumps(payload, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" file_edit ")

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        conns = list(self._subs.get(chat_id, ()))
        meta = metadata or {}
        stream_key = (chat_id, str(stream_id or ""))
        completed_text: str | None = None
        if stream_end:
            body: dict[str, Any] = {"event": "stream_end", "chat_id": chat_id}
            buffered = (
                self._stream_text_buffers.setdefault(stream_key, [])
                if merge_next
                else self._stream_text_buffers.pop(stream_key, [])
            )
            if delta:
                buffered.append(delta)
            full_text = "".join(buffered)
            rewritten = self._media.rewrite_local_markdown_images(full_text)
            completed_text = rewritten
            if delta or rewritten != full_text:
                body["text"] = rewritten
        else:
            body = {
                "event": "delta",
                "chat_id": chat_id,
                "text": delta,
            }
            self._stream_text_buffers.setdefault(stream_key, []).append(delta)
        if stream_id is not None:
            body["stream_id"] = stream_id
        if stream_end and resuming:
            body["resuming"] = True
        if stream_end and merge_next:
            body["merge_next"] = True
        self._persist_turn_stream_event(
            chat_id,
            body,
            completed_text=completed_text,
            metadata=meta,
            phase="answer",
            include_source=True,
        )
        raw = json.dumps(body, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" stream ")

    async def send_turn_end(
        self,
        chat_id: str,
        latency_ms: int | None = None,
        *,
        goal_state: dict[str, Any] | None = None,
        usage: LLMUsage | None = None,
        context_window_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        turn_owner: str | None = None,
    ) -> None:
        """Signal that the agent has fully finished processing the current turn."""
        conns = list(self._subs.get(chat_id, ()))
        body: dict[str, Any] = {"event": "turn_end", "chat_id": chat_id}
        turn_id = (metadata or {}).get(WEBUI_TURN_METADATA_KEY)
        if isinstance(turn_id, str) and turn_id:
            body["turn_id"] = turn_id
        if latency_ms is not None:
            body["latency_ms"] = int(latency_ms)
        if goal_state is not None:
            body["goal_state"] = goal_state
        if usage is not None:
            body["usage"] = usage.to_turn_dict()
        if context_window_tokens is not None:
            body["context_window_tokens"] = int(context_window_tokens)
        canonical_webui_turn = (metadata or {}).get("webui") is True
        prior_persistence_failure = (
            canonical_webui_turn
            and websocket_turn_transcript_persistence_failed(chat_id, turn_owner)
        )
        persisted = self._persist_turn_transcript_event(
            chat_id,
            body,
            metadata=metadata,
            phase="complete",
            transcript_overrides=(
                {WEBUI_TRANSCRIPT_INCOMPLETE_KEY: True}
                if prior_persistence_failure
                else None
            ),
        )
        if persisted:
            # A successful completion either has a complete transcript or now
            # carries a durable incomplete marker. The HTTP replay path can
            # recover the latter from session history after a gateway restart.
            clear_websocket_turn_if_current(chat_id, turn_owner)
        self._clear_stream_buffers(chat_id)
        raw = json.dumps(body, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_end ")

    async def send_recovery_state(
        self,
        chat_id: str,
        event: RecoveryStateEvent,
    ) -> None:
        """Publish one structured recovery transition without chat pollution."""
        body: dict[str, Any] = {
            "event": "recovery_state",
            "chat_id": chat_id,
            "status": event.status,
            "recovery_id": event.recovery_id,
            "attempts": event.attempts,
        }
        if event.reason:
            body["reason"] = event.reason
        if event.can_continue is not None:
            body["can_continue"] = event.can_continue
        raw = json.dumps(body, ensure_ascii=False)
        for connection in list(self._subs.get(chat_id, ())):
            await self._safe_send_to(connection, raw, label=" recovery_state ")

    async def send_goal_state(self, chat_id: str, blob: dict[str, Any]) -> None:
        """Push persisted goal-state snapshot for *chat_id* (multi-chat isolation)."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body = {"event": "goal_state", "chat_id": chat_id, "goal_state": blob}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" goal_state ")

    async def send_goal_status(
        self,
        chat_id: str,
        status: str,
        *,
        started_at: float | None = None,
        turn_id: str | None = None,
    ) -> None:
        """Notify subscribed clients that a turn started or finished (wall-clock hint)."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {
            "event": "goal_status",
            "chat_id": chat_id,
            "status": status,
        }
        if status == "running" and started_at is not None:
            body["started_at"] = started_at
        if turn_id:
            body["turn_id"] = turn_id
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" goal_status ")

    async def send_session_updated(self, chat_id: str, *, scope: str | None = None) -> None:
        """Notify WebUI clients that a session row should refresh."""
        conns = list(self._conn_chats)
        if not conns:
            return
        body: dict[str, Any] = {"event": "session_updated", "chat_id": chat_id}
        if scope:
            body["scope"] = scope
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" session_updated ")

    async def send_user_input(
        self,
        chat_id: str,
        *,
        content: str,
        created_at_ms: int,
        provenance: dict[str, Any],
    ) -> None:
        """Project user input produced outside a WebSocket connection."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {
            "event": "user_message",
            "chat_id": chat_id,
            "text": content,
            "created_at_ms": created_at_ms,
            "starts_turn": False,
        }
        if provenance:
            body["provenance"] = provenance
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" user_message ")

    async def send_runtime_model_updated(
        self,
        *,
        model_name: Any,
        model_preset: Any = None,
    ) -> None:
        """Broadcast runtime model changes to every open websocket connection."""
        conns = list(self._conn_chats)
        if not conns or not isinstance(model_name, str) or not model_name.strip():
            return
        body: dict[str, Any] = {
            "event": "runtime_model_updated",
            "model_name": model_name.strip(),
        }
        if isinstance(model_preset, str) and model_preset.strip():
            body["model_preset"] = model_preset.strip()
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" runtime_model_updated ")

    async def send_turn_model_updated(
        self,
        chat_id: str,
        *,
        model_name: Any,
        model_preset: Any = None,
        context_window_tokens: Any = None,
        fallback: bool = False,
    ) -> None:
        """Notify one chat's subscribers which model is handling its current request."""
        conns = list(self._subs.get(chat_id, ()))
        if (
            not conns
            or not isinstance(model_name, str)
            or not model_name.strip()
        ):
            return
        body: dict[str, Any] = {
            "event": "turn_model_updated",
            "chat_id": chat_id,
            "model_name": model_name.strip(),
        }
        if isinstance(model_preset, str) and model_preset.strip():
            body["model_preset"] = model_preset.strip()
        if isinstance(context_window_tokens, int) and context_window_tokens > 0:
            body["context_window_tokens"] = context_window_tokens
        if fallback:
            body["fallback"] = True
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_model_updated ")
