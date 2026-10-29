"""WebSocket server channel: nanobot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import json
import socket
import ssl
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self, TypeGuard, cast
from urllib.parse import urlsplit, urlunsplit
from weakref import WeakSet

from pydantic import Field, PrivateAttr, field_validator, model_validator
from websockets.asyncio.server import Server, ServerConnection, serve, unix_serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response as WsResponse
from websockets.protocol import CONNECTING

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.websocket.binary_http import BinaryHTTPBridge
from nanobot.config_base import Base
from nanobot.runtime_admission import RuntimeMaintenanceError
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
from nanobot.webui.outbound_delivery import ChatAudience, WebUIAudience, WebUIOutboundDelivery
from nanobot.webui.session_identity import is_valid_webui_chat_id
from nanobot.webui.websocket_logging import websockets_server_logger

# Plain HTTP WebUI routes also run through websockets.process_request.
_WEBUI_HTTP_OPEN_TIMEOUT_S = 360.0
_LISTENER_CHECK_INTERVAL_S = 0.5
_LISTENER_STABLE_AFTER_S = 30.0
_LISTENER_RESTART_BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

# Outbound delivery is isolated per connection.  A bounded queue keeps a slow
# or suspended terminal from retaining an unbounded stream in server memory.
_OUTBOUND_QUEUE_MAX_FRAMES = 256
_OUTBOUND_QUEUE_MAX_BYTES = 8 * 1024 * 1024
_OUTBOUND_SEND_TIMEOUT_S = 10.0
_OUTBOUND_CLOSE_TIMEOUT_S = 1.0

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
    # Keep the existing configurable guard (also used for non-attachment
    # frames and older clients). HTTP attachments are outside this limit.
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


@dataclass(slots=True)
class _OutboundFrame:
    raw: str
    utf8_bytes: int
    label: str


@dataclass(slots=True)
class _ConnectionOutbound:
    queue: asyncio.Queue[_OutboundFrame]
    buffered_bytes: int = 0
    writer: asyncio.Task[None] | None = None
    closing: bool = False


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
        self._connection_outbound: dict[ServerConnection, _ConnectionOutbound] = {}
        self._outbound_retire_tasks: set[asyncio.Task[None]] = set()
        self._retired_connections: WeakSet[ServerConnection] = WeakSet()

        self.gateway = gateway
        self._uploads = gateway.uploads
        self._outbound = WebUIOutboundDelivery(
            self,
            media=gateway.media,
            transcripts=gateway.transcripts,
            temporary_chats=gateway.temporary_chats,
            session_projection=gateway.session_projection,
        )
        self._commands = WebUICommandRouter(self, gateway, outbound=self._outbound)
        self._webui_request_tasks = self._commands.request_tasks
        self._webui_request_operations = self._commands.request_operations
        self._webui_request_locks = self._commands.request_locks

    # -- Subscription bookkeeping -------------------------------------------

    def webui_subscribers(self, chat_id: str) -> tuple[ServerConnection, ...]:
        """Return a stable snapshot of one chat's transport subscribers."""
        return tuple(self._subs.get(chat_id, ()))

    def webui_recipients(self, audience: WebUIAudience) -> tuple[ServerConnection, ...]:
        """Snapshot the selected audience without interpreting its public frames."""
        if isinstance(audience, ChatAudience):
            return self.webui_subscribers(audience.chat_id)
        if audience == "authenticated_webui":
            return tuple(self._webui_connections)
        return tuple(self._conn_chats)

    def webui_connection_chats(self, connection: ServerConnection) -> tuple[str, ...]:
        return tuple(self._conn_chats.get(connection, ()))

    def webui_attach(self, connection: ServerConnection, chat_id: str) -> None:
        self._attach(connection, chat_id)

    def webui_detach(self, connection: ServerConnection, chat_id: str) -> None:
        self._detach(connection, chat_id)

    def webui_clear_connection_default(self, connection: ServerConnection) -> None:
        self._conn_default.pop(connection, None)

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
        session_generation: str | None,
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
            session_generation=session_generation,
        )

    def _attach(self, connection: ServerConnection, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        if not self._register_connection_outbound(connection):
            return
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _register_connection_outbound(self, connection: ServerConnection) -> bool:
        if connection in self._retired_connections:
            return False
        self._connection_outbound.setdefault(
            connection,
            _ConnectionOutbound(asyncio.Queue(maxsize=_OUTBOUND_QUEUE_MAX_FRAMES)),
        )
        return True

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

    async def _cleanup_connection(self, connection: ServerConnection) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        self._retired_connections.add(connection)
        self._uploads.revoke(connection)
        state = self._connection_outbound.get(connection)
        if state is not None:
            state.closing = True
            await self._stop_connection_writer(state)
        try:
            await self._commands.cleanup_connection(connection)
        finally:
            for chat_id in tuple(self._conn_chats.get(connection, ())):
                self._detach(connection, chat_id)
            self._conn_default.pop(connection, None)
            self.gateway.endpoint.discard_connection(connection)
            if self._connection_outbound.get(connection) is state:
                self._connection_outbound.pop(connection, None)

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
        await self._safe_send_to(connection, raw, label=f" {event} ")

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebSocketConfig().model_dump(by_alias=True)

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

    # -- Server lifecycle and connection ingress ---------------------------

    @staticmethod
    def _socket_is_accepting(sock: socket.socket) -> bool:
        """Return whether a bound socket still advertises a listen capability.

        ``SO_ACCEPTCONN`` is not portable: macOS/BSD raise ``OSError`` with
        ``ENOPROTOOPT`` ("Protocol not available") for this option even on a
        perfectly healthy listening socket. Treating that as "not serving"
        makes the listener look permanently degraded, so the caller retries
        forever and the channel never reaches a ready state. When the option
        is unavailable we fall back to the file-descriptor liveness check.
        """
        if sock.fileno() < 0:
            return False
        try:
            return bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
        except OSError as exc:
            if exc.errno in (errno.ENOPROTOOPT, errno.EOPNOTSUPP):
                return True
            raise

    @classmethod
    def _listener_is_serving(cls, server: Server) -> bool:
        """Return whether every bound socket still has a live listen capability."""
        try:
            sockets = server.sockets
            return bool(sockets) and server.is_serving() and all(
                cls._socket_is_accepting(sock) for sock in sockets
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

    async def _close_server(
        self, server: Server, socket_path: str, bridge: BinaryHTTPBridge,
    ) -> None:
        server.close()
        try:
            await bridge.shutdown()
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
        await self._outbound.initialize()
        self.gateway.http.remote_instances.resume()
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

        def process_response(
            connection: ServerConnection, _request: WsRequest, response: WsResponse,
        ) -> WsResponse:
            # Stay synchronous: websockets sends immediately after this hook returns.
            if connection.state is not CONNECTING:
                exc = connection.protocol.handshake_exc
                if exc is not None:
                    connection.logger.error(
                        "opening handshake failed", exc_info=(type(exc), exc, exc.__traceback__),
                    )
                # The request callback finished; cancel only this connection's handshake.
                raise asyncio.CancelledError("Peer disconnected before handshake response")
            return response

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        from aiohttp import web

        async def handle_binary(request: web.BaseRequest) -> web.StreamResponse:
            try:
                with self.bus.admission.activity():
                    return await self._uploads.handle(request)
            except RuntimeMaintenanceError:
                return web.json_response({"error": "Gateway update is being verified"}, status=503)

        async def prune_uploads() -> None:
            while not stop_event.is_set():
                self._uploads.store.prune()
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30)
                except TimeoutError:
                    pass

        prune_task = asyncio.create_task(prune_uploads())

        async def runner() -> None:
            socket_path = self.config.unix_socket_path
            failures = 0
            while not stop_event.is_set():
                server: Server | None = None
                bridge = BinaryHTTPBridge(handle_binary)
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
                            process_response=process_response,
                            create_connection=bridge.connection_factory,
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
                            process_response=process_response,
                            create_connection=bridge.connection_factory,
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
                        await self._close_server(server, socket_path, bridge)
                    else:
                        await bridge.shutdown()
                    if self._server is server:
                        self._server = None

        disconnect_pairing = self._outbound.bind_pairing(self.bus, channel=self.name)
        task = asyncio.create_task(runner())
        self._server_task = task
        try:
            await task
        finally:
            disconnect_pairing()
            prune_task.cancel()
            await asyncio.gather(prune_task, return_exceptions=True)
            self._uploads.store.clear()
            self._running = False
            if self._server_task is task:
                self._server_task = None

    async def _connection_loop(self, connection: ServerConnection) -> None:
        self._retired_connections.discard(connection)
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
        from nanobot.webui.client_contract import gateway_identity

        try:
            await connection.send(
                json.dumps(
                    {
                        "event": "ready",
                        "chat_id": default_chat_id,
                        "client_id": client_id,
                        **({"upload": self._uploads.issue(connection)}
                           if self.is_allowed(client_id) else {}),
                        **({"terminal": gateway_identity(self.gateway.tokens.instance_id)}
                           if _query_first(query, "terminal_protocol") == "1" else {}),
                    },
                    ensure_ascii=False,
                )
            )
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._conn_default[connection] = default_chat_id
            self._attach(connection, default_chat_id)
            await self._outbound.hydrate(default_chat_id)

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
        await self._dispatch_active_envelope(connection, client_id, envelope)

    async def _dispatch_active_envelope(
        self,
        connection: ServerConnection,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        if not self._register_connection_outbound(connection):
            return
        await self._commands.dispatch(connection, client_id, envelope)

    # -- Outbound WebSocket events -----------------------------------------

    async def stop(self) -> None:
        await self.gateway.http.remote_instances.close()
        server_task = self._server_task
        if (
            not self._running
            and server_task is None
            and not self._connection_outbound
            and not self._outbound_retire_tasks
        ):
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        for connection in tuple(self._connection_outbound):
            await self._cleanup_connection(connection)
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
        retire_tasks = tuple(self._outbound_retire_tasks)
        if retire_tasks:
            await asyncio.gather(*retire_tasks, return_exceptions=True)
        await self._commands.close()
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()

    @staticmethod
    async def _stop_connection_writer(state: _ConnectionOutbound) -> None:
        task = state.writer
        current = asyncio.current_task()
        if task is not None and task is not current and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        while True:
            try:
                state.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        state.buffered_bytes = 0

    def _start_connection_writer(
        self,
        connection: ServerConnection,
        state: _ConnectionOutbound,
    ) -> None:
        if state.closing or (state.writer is not None and not state.writer.done()):
            return
        state.writer = asyncio.create_task(
            self._drain_connection_outbound(connection, state),
            name=f"websocket-outbound-{id(connection):x}",
        )

    @property
    def has_pending_delivery(self) -> bool:
        # send() only enqueues a frame. buffered_bytes includes the frame that
        # a writer has removed from its queue but has not finished transmitting.
        return bool(self._outbound_retire_tasks) or any(
            state.buffered_bytes or not state.queue.empty()
            or (state.writer is not None and not state.writer.done())
            for state in self._connection_outbound.values()
        )

    async def _drain_connection_outbound(
        self,
        connection: ServerConnection,
        state: _ConnectionOutbound,
    ) -> None:
        current = asyncio.current_task()
        try:
            while not state.closing:
                try:
                    frame = state.queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    async with asyncio.timeout(_OUTBOUND_SEND_TIMEOUT_S):
                        await connection.send(frame.raw)
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    self.logger.warning("connection send timed out{}", frame.label)
                    self._schedule_connection_retirement(
                        connection,
                        state,
                        close_connection=True,
                        close_code=1013,
                        close_reason="outbound send timeout",
                    )
                    return
                except ConnectionClosed:
                    self.logger.warning("connection gone{}", frame.label)
                    self._schedule_connection_retirement(
                        connection,
                        state,
                        close_connection=False,
                    )
                    return
                except Exception:
                    self.logger.exception("send failed{}", frame.label)
                    self._schedule_connection_retirement(
                        connection,
                        state,
                        close_connection=True,
                        close_code=1011,
                        close_reason="outbound send failed",
                    )
                    return
                finally:
                    state.buffered_bytes = max(0, state.buffered_bytes - frame.utf8_bytes)
        finally:
            if state.writer is current:
                state.writer = None
            if not state.closing and not state.queue.empty():
                self._start_connection_writer(connection, state)

    def _schedule_connection_retirement(
        self,
        connection: ServerConnection,
        state: _ConnectionOutbound,
        *,
        close_connection: bool,
        close_code: int = 1000,
        close_reason: str = "",
    ) -> None:
        if state.closing:
            return
        state.closing = True
        task = asyncio.create_task(
            self._retire_connection(
                connection,
                close_connection=close_connection,
                close_code=close_code,
                close_reason=close_reason,
            ),
            name=f"websocket-retire-{id(connection):x}",
        )
        self._outbound_retire_tasks.add(task)
        task.add_done_callback(self._outbound_retire_tasks.discard)

    async def _retire_connection(
        self,
        connection: ServerConnection,
        *,
        close_connection: bool,
        close_code: int,
        close_reason: str,
    ) -> None:
        try:
            if close_connection:
                try:
                    async with asyncio.timeout(_OUTBOUND_CLOSE_TIMEOUT_S):
                        await connection.close(code=close_code, reason=close_reason)
                except TimeoutError:
                    self.logger.warning("timed out closing slow WebSocket connection")
                    with suppress(Exception):
                        connection.transport.abort()
                except ConnectionClosed:
                    pass
                except Exception:
                    self.logger.exception("failed to close WebSocket connection")
                    with suppress(Exception):
                        connection.transport.abort()
        finally:
            try:
                await self._cleanup_connection(connection)
            except Exception:
                self.logger.exception("failed to clean up WebSocket connection")

    async def _safe_send_to(
        self,
        connection: ServerConnection,
        raw: str,
        *,
        label: str = "",
    ) -> None:
        """Queue one frame without letting this connection block other clients."""
        state = self._connection_outbound.get(connection)
        if state is None or state.closing:
            return
        utf8_bytes = len(raw.encode("utf-8"))
        if state.queue.full() or state.buffered_bytes + utf8_bytes > _OUTBOUND_QUEUE_MAX_BYTES:
            self.logger.warning(
                "disconnecting slow WebSocket connection: outbound queue full "
                "({} frames, {} bytes)",
                state.queue.qsize(),
                state.buffered_bytes,
            )
            self._schedule_connection_retirement(
                connection,
                state,
                close_connection=True,
                close_code=1013,
                close_reason="outbound queue full",
            )
            await asyncio.sleep(0)
            return
        try:
            state.queue.put_nowait(_OutboundFrame(raw, utf8_bytes, label))
        except asyncio.QueueFull:
            self._schedule_connection_retirement(
                connection,
                state,
                close_connection=True,
                close_code=1013,
                close_reason="outbound queue full",
            )
            await asyncio.sleep(0)
            return
        state.buffered_bytes += utf8_bytes
        self._start_connection_writer(connection, state)
        # Give an idle writer a chance to start without waiting for physical I/O.
        await asyncio.sleep(0)

    async def send(self, msg: OutboundMessage) -> None:
        await self._outbound.send(msg)

    def prepare_tool_events(self, msg: OutboundMessage) -> OutboundMessage:
        return msg

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        await self._outbound.send_reasoning_delta(chat_id, delta, metadata, stream_id=stream_id)

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        await self._outbound.send_reasoning_end(chat_id, metadata, stream_id=stream_id)

    async def send_file_edit_events(
        self,
        chat_id: str,
        edits: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._outbound.send_file_edit_events(chat_id, edits, metadata)

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
        await self._outbound.send_delta(
            chat_id, delta, metadata, stream_id=stream_id,
            stream_end=stream_end, resuming=resuming, merge_next=merge_next,
        )
