"""WebSocket server channel: nanobot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import ssl
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self, TypeGuard, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, PrivateAttr, field_validator, model_validator
from websockets.asyncio.server import ServerConnection, serve, unix_serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest

from nanobot.bus.events import (
    INBOUND_META_USER_SHELL,
    OUTBOUND_META_AGENT_UI,
    OutboundMessage,
)
from nanobot.bus.outbound_events import (
    GoalStateSyncEvent,
    GoalStatusEvent,
    ProgressEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
    TurnModelUpdatedEvent,
    UserInputEvent,
    outbound_event_from_message,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.command.builtin import USER_SHELL_COMMAND, builtin_command_starts_agent_turn
from nanobot.config.schema import Base
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_INPUT_META,
    WEBUI_QUOTE_METADATA,
    RuntimeContextBlock,
    webui_quote_runtime_context,
)
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScopeError,
)
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.webui_turns import (
    clear_websocket_turn_if_current,
    clear_websocket_turns,
    mark_websocket_turn_transcript_persistence_failed,
    register_queued_websocket_turn_if_idle,
    websocket_turn_id,
    websocket_turn_transcript_persistence_failed,
    websocket_turn_wall_started_at,
)
from nanobot.utils.helpers import safe_filename
from nanobot.webui.cli_apps_api import normalize_cli_app_mentions
from nanobot.webui.forking import handle_webui_fork_chat
from nanobot.webui.gateway_services import GatewayServices
from nanobot.webui.http_utils import (
    is_trusted_proxy_authenticated_request as _is_trusted_proxy_authenticated_request,
)
from nanobot.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from nanobot.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from nanobot.webui.http_utils import (
    query_first as _query_first,
)
from nanobot.webui.mcp_presets_api import normalize_mcp_preset_mentions
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_SYSTEM_COMMAND_TURN_PREFIX,
    WEBUI_TURN_METADATA_KEY,
)
from nanobot.webui.session_access import (
    SessionMention,
    WebuiSessionAccess,
    session_mentions_runtime_context,
)
from nanobot.webui.sidebar_state import write_webui_sidebar_state
from nanobot.webui.temporary_chats import TemporaryChatError
from nanobot.webui.transcript import WEBUI_TRANSCRIPT_INCOMPLETE_KEY
from nanobot.webui.transcription_ws import webui_transcription_event
from nanobot.webui.websocket_logging import websockets_server_logger

# Plain HTTP WebUI routes also run through websockets.process_request.
_WEBUI_HTTP_OPEN_TIMEOUT_S = 360.0
_WEBUI_REQUEST_CACHE_TTL_S = 5 * 60.0
_WEBUI_REQUEST_CACHE_MAX = 256


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


# Accept UUIDs and short scoped keys like "unified:default". Keeps the capability
# namespace small enough to rule out path traversal / quote injection tricks.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def _is_valid_chat_id(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and _CHAT_ID_RE.match(value) is not None


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


def _is_websocket_upgrade(request: WsRequest) -> bool:
    """Detect an actual WS upgrade; plain HTTP GETs to the same path should fall through."""
    upgrade = request.headers.get("Upgrade") or request.headers.get("upgrade")
    connection = request.headers.get("Connection") or request.headers.get("connection")
    if not upgrade or "websocket" not in upgrade.lower():
        return False
    if not connection or "upgrade" not in connection.lower():
        return False
    return True


@dataclass(frozen=True)
class _WebUIRequestResult:
    result: Any = None
    status: int | None = None
    message: str | None = None


@dataclass
class _WebUIRequestOperation:
    action: str
    payload_digest: bytes
    task: asyncio.Task[_WebUIRequestResult]
    completed_at: float | None = None


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
        self._webui_connections: set[ServerConnection] = set()
        # Delivery tasks are connection-bound, while operations are keyed only
        # by request_id so reconnect retries join or replay the original work.
        self._webui_request_tasks: dict[
            tuple[ServerConnection, str],
            asyncio.Task[None],
        ] = {}
        self._webui_request_operations: dict[str, _WebUIRequestOperation] = {}
        # Preserve request/response order for mutations from one
        # UI. Without this, an earlier slow settings response can overwrite a
        # newer settings snapshot in the client.
        self._webui_request_locks: dict[ServerConnection, asyncio.Lock] = {}
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None

        self.gateway = gateway
        self._http_router = gateway.http
        self._tokens = gateway.tokens
        self._media = gateway.media
        self._ingress = gateway.ingress
        self._transcripts = gateway.transcripts
        self._workspaces = gateway.workspaces
        self._temporary_chats = gateway.temporary_chats
        self._session_access = (
            WebuiSessionAccess(gateway.session_manager)
            if gateway.session_manager is not None
            else None
        )

        self._stream_text_buffers: dict[tuple[str, str], list[str]] = {}

    # -- Subscription bookkeeping -------------------------------------------

    def _workspace_controls_available(self, connection: ServerConnection) -> bool:
        return self._http_router.workspace_controls_available(connection)

    def _attach(self, connection: ServerConnection, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _attached_model_fields(self, chat_id: str) -> dict[str, Any]:
        """Expose small session runtime facts on the attach handshake."""
        sessions = self.gateway.session_manager
        if sessions is None:
            return {}
        snapshot = sessions.read_session_metadata(f"websocket:{chat_id}")
        raw_metadata = snapshot.get("metadata") if snapshot is not None else None
        metadata = cast(dict[str, object], raw_metadata) if isinstance(raw_metadata, dict) else None
        fields: dict[str, Any] = {}
        try:
            fields["model_preset"] = model_preset_from_metadata(metadata)
        except ValueError:
            self.logger.warning("ignoring invalid model preset metadata for chat_id={}", chat_id)
            fields["model_preset"] = None
        if isinstance(metadata, dict):
            usage = metadata.get("_last_usage")
            if isinstance(usage, dict):
                sanitized_usage: dict[str, int | float] = {}
                for key, value in cast(dict[object, object], usage).items():
                    if (
                        isinstance(key, str)
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        sanitized_usage[key] = value
                fields["usage"] = sanitized_usage
        return fields

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

    async def _discard_connection_owned_chat(
        self,
        connection: ServerConnection,
        chat_id: str,
    ) -> None:
        await self._temporary_chats.discard(connection, chat_id)
        self._detach(connection, chat_id)
        clear_websocket_turns(chat_id)
        self._clear_stream_buffers(chat_id)

    async def send_webui_protocol_error(
        self,
        connection: ServerConnection,
        detail: str,
    ) -> None:
        """Send a stable protocol error from a WebUI-owned orchestration helper."""
        await self._send_event(connection, "error", detail=detail)

    async def attach_webui_fork(
        self,
        connection: ServerConnection,
        *,
        fork_id: str,
        fork_key: str,
    ) -> None:
        """Attach and hydrate a newly created WebUI chat fork."""
        scope = self._workspaces.scope_for_session_key(fork_key)
        self._attach(connection, fork_id)
        await self._send_event(
            connection,
            "attached",
            chat_id=fork_id,
            **self._attached_model_fields(fork_id),
        )
        await self._send_event(
            connection,
            "session_updated",
            chat_id=fork_id,
            scope="metadata",
            workspace_scope=scope.payload(),
        )
        await self._hydrate_after_subscribe(fork_id)

    async def _cleanup_connection(self, connection: ServerConnection) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        chat_ids = tuple(self._conn_chats.get(connection, ()))
        for cid in chat_ids:
            if self._temporary_chats.owns(connection, cid):
                await self._discard_connection_owned_chat(connection, cid)
            else:
                self._detach(connection, cid)
        for cid in self._temporary_chats.chat_ids_for_owner(connection):
            await self._discard_connection_owned_chat(connection, cid)
        self._conn_default.pop(connection, None)
        self._webui_connections.discard(connection)
        self._discard_webui_request_lock_if_idle(connection)

    async def _maybe_push_persisted_goal_state(self, chat_id: str) -> None:
        """Replay actionable goal state after *chat_id* is subscribed.

        Goal metadata lives on the session JSONL and survives gateway restarts, but
        connected clients normally see it via ``goal_state`` / ``turn_end`` frames.
        Pushing here makes refresh + reconnect restore the strip without a new model turn.
        """
        if self.gateway.session_manager is None:
            return
        row = self.gateway.session_manager.read_session_file(f"websocket:{chat_id}")
        row_data = row if isinstance(row, dict) else {}
        meta = row_data.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        blob = goal_state_ws_blob(cast(dict[str, Any], meta))
        if not blob.get("active") and blob.get("status") != "blocked":
            return
        await self.send_goal_state(chat_id, blob)

    async def _maybe_push_turn_run_wall_clock(self, chat_id: str) -> None:
        """Replay ``goal_status: running`` when a turn is still active (same-process refresh)."""
        t0 = websocket_turn_wall_started_at(chat_id)
        if t0 is None:
            return
        await self.send_goal_status(
            chat_id,
            "running",
            started_at=t0,
            turn_id=websocket_turn_id(chat_id),
        )

    async def _hydrate_after_subscribe(self, chat_id: str) -> None:
        """Replay persisted or actively running per-chat state after subscribe."""
        await self._maybe_push_persisted_goal_state(chat_id)
        await self._maybe_push_turn_run_wall_clock(chat_id)

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

    async def _broadcast_webui_event(self, event: str, **fields: Any) -> None:
        for connection in tuple(self._webui_connections):
            await self._send_event(connection, event, **fields)

    async def _broadcast_user_message(
        self,
        origin: ServerConnection,
        chat_id: str,
        text: str,
        *,
        turn_id: str | None,
        starts_turn: bool,
        media_paths: list[str],
        media_names: list[str | None],
        cli_apps: list[dict[str, Any]],
        mcp_presets: list[dict[str, Any]],
        session_mentions: list[SessionMention],
    ) -> None:
        """Project one accepted user message to the other clients on the chat.

        The origin already has an optimistic row and receives canonical turn
        ownership in ``message_accepted``. Peers need the ingress projection.
        """
        body: dict[str, Any] = {
            "event": "user_message",
            "chat_id": chat_id,
            "text": text,
            "starts_turn": starts_turn,
        }
        if turn_id is not None:
            body["turn_id"] = turn_id
        media = self._media.augment_transcript_user_media(media_paths)
        for attachment, name in zip(media, media_names, strict=False):
            if name:
                attachment["name"] = name
        if media:
            body["media_urls"] = media
        if cli_apps:
            body["cli_apps"] = cli_apps
        if mcp_presets:
            body["mcp_presets"] = mcp_presets
        if session_mentions:
            body["session_mentions"] = session_mentions
        active_turn_id = websocket_turn_id(chat_id)
        if active_turn_id is not None:
            body["active_turn_id"] = active_turn_id
        started_at = websocket_turn_wall_started_at(chat_id)
        if active_turn_id is not None and started_at is not None:
            body["started_at"] = started_at
        raw = json.dumps(body, ensure_ascii=False)
        for connection in tuple(self._subs.get(chat_id, ())):
            if connection is origin:
                continue
            await self._safe_send_to(connection, raw, label=" user_message ")

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
        """Route an inbound HTTP request to the HTTP handler or WS upgrade."""
        got, query = _parse_request_path(request.path)
        expected_ws = self._expected_path()

        # WebSocket upgrade — channel handles this itself
        if got == expected_ws and _is_websocket_upgrade(request):
            client_id = _query_first(query, "client_id") or ""
            if len(client_id) > 128:
                client_id = client_id[:128]
            if not self.is_allowed(client_id):
                return connection.respond(403, "Forbidden")
            return self._authorize_websocket_handshake(connection, query, request.headers)

        # Everything else goes to the HTTP handler
        return await self._http_router.dispatch(connection, request)

    def _authorize_websocket_handshake(
        self,
        connection: ServerConnection,
        query: dict[str, list[str]],
        headers: Any = None,
    ) -> Any:
        if _is_trusted_proxy_authenticated_request(connection, headers or {}, self.config):
            self._webui_connections.add(connection)
            return None

        supplied = _query_first(query, "token")
        static_token = self.config.token.strip()

        if static_token:
            if supplied and hmac.compare_digest(supplied, static_token):
                return None
            if supplied and self._consume_issued_token(connection, supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if self.config.websocket_requires_token:
            if supplied and self._consume_issued_token(connection, supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if supplied:
            self._consume_issued_token(connection, supplied)
        return None

    def _consume_issued_token(self, connection: ServerConnection, token: str) -> bool:
        audience = self._tokens.take_issued_token_audience(token)
        if audience == "webui":
            self._webui_connections.add(connection)
        return audience is not None

    # -- Server lifecycle and connection ingress ---------------------------

    async def start(self) -> None:
        from nanobot.utils.logging_bridge import redirect_lib_logging

        redirect_lib_logging("websockets", level="WARNING")
        ws_logger = websockets_server_logger()

        self._running = True
        self._stop_event = asyncio.Event()

        ssl_context = self._build_ssl_context()
        scheme = "wss" if ssl_context else "ws"

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            return await self._dispatch_http(connection, request)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

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
                    f"unix:{self.config.unix_socket_path}{_normalize_config_path(self.config.token_issue_path)}"
                    if self.config.unix_socket_path
                    else (
                        f"{scheme}://{self.config.host}:{self.config.port}"
                        f"{_normalize_config_path(self.config.token_issue_path)}"
                    )
                ),
            )

        async def runner() -> None:
            socket_path = self.config.unix_socket_path
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
            try:
                assert self._stop_event is not None
                await self._stop_event.wait()
            finally:
                server.close()
                await server.wait_closed()
                if socket_path:
                    with suppress(FileNotFoundError):
                        Path(socket_path).unlink()

        self._server_task = asyncio.create_task(runner())
        await self._server_task

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
        """Route one typed inbound envelope (``new_chat`` / ``attach`` / ``message``)."""
        t = envelope.get("type")
        if t == "webui_request":
            await self._start_webui_request(connection, envelope)
            return
        if t == "new_chat":
            new_id = str(uuid.uuid4())
            scope = await self._workspace_scope_or_error(
                connection,
                lambda: self._workspaces.scope_for_new_chat(
                    envelope,
                    controls_available=self._workspace_controls_available(connection),
                ),
            )
            if scope is None:
                return
            self._workspaces.persist_scope(new_id, scope)
            self._attach(connection, new_id)
            await self._send_event(
                connection,
                "attached",
                chat_id=new_id,
                **self._attached_model_fields(new_id),
            )
            await self._send_event(
                connection,
                "session_updated",
                chat_id=new_id,
                scope="metadata",
                workspace_scope=scope.payload(),
            )
            await self._hydrate_after_subscribe(new_id)
            return
        if t == "new_temporary_chat":
            try:
                new_id = self._temporary_chats.create(
                    connection,
                    trusted_webui=connection in self._webui_connections,
                )
            except TemporaryChatError as exc:
                await self._send_event(connection, "error", detail=exc.detail)
                return
            self._attach(connection, new_id)
            await self._send_event(
                connection,
                "attached",
                chat_id=new_id,
                temporary=True,
            )
            return
        if t == "fork_chat":
            await handle_webui_fork_chat(self, connection, envelope)
            return
        if t == "discard_temporary_chat":
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid temporary chat_id")
                return
            try:
                await self._discard_connection_owned_chat(connection, cid)
            except TemporaryChatError as exc:
                await self._send_event(connection, "error", detail=exc.detail, chat_id=cid)
            return
        if t == "attach":
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            try:
                self._temporary_chats.validate_attach(cid)
            except TemporaryChatError as exc:
                await self._send_event(connection, "error", detail=exc.detail, chat_id=cid)
                return
            self._attach(connection, cid)
            await self._send_event(
                connection,
                "attached",
                chat_id=cid,
                **self._attached_model_fields(cid),
            )
            await self._hydrate_after_subscribe(cid)
            return
        if t == "set_sidebar_state":
            if connection not in self._webui_connections:
                await self._send_event(connection, "error", detail="access_denied")
                return
            state = envelope.get("state")
            if not isinstance(state, dict):
                await self._send_event(
                    connection,
                    "error",
                    detail="invalid_sidebar_state",
                )
                return
            try:
                saved_state = await asyncio.to_thread(
                    write_webui_sidebar_state,
                    cast(dict[str, Any], state),
                )
            except (OSError, ValueError):
                await self._send_event(
                    connection,
                    "error",
                    detail="invalid_sidebar_state",
                )
                return
            await self._broadcast_webui_event(
                "sidebar_state_updated",
                state=saved_state,
            )
            return
        if t == "set_workspace_scope":
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            try:
                self._temporary_chats.validate_workspace_update(cid)
            except TemporaryChatError as exc:
                await self._send_event(connection, "error", detail=exc.detail, chat_id=cid)
                return
            scope = await self._workspace_scope_or_error(
                connection,
                lambda: self._workspaces.scope_for_set_request(
                    envelope,
                    chat_id=cid,
                    chat_running=websocket_turn_wall_started_at(cid) is not None,
                    controls_available=self._workspace_controls_available(connection),
                ),
                chat_id=cid,
            )
            if scope is None:
                return
            self._workspaces.persist_scope(cid, scope)
            # Other clients on the same gateway only need an invalidation; they
            # can reload the authoritative session row without receiving a
            # local project path that belongs to another connection.
            await self.send_session_updated(cid, scope="metadata")
            await self._send_event(
                connection,
                "session_updated",
                chat_id=cid,
                scope="metadata",
                workspace_scope=scope.payload(),
            )
            return
        if t == "transcribe_audio":
            event, payload = await webui_transcription_event(
                envelope,
                config_path=self.gateway.settings.config.path,
            )
            await self._send_event(connection, event, **payload)
            return
        if t == "message":
            cid = envelope.get("chat_id")
            content = envelope.get("content")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            raw_turn_id = envelope.get("turn_id")
            turn_id = raw_turn_id if isinstance(raw_turn_id, str) and raw_turn_id else None
            rejection_fields = {
                "chat_id": cid,
                **({"turn_id": turn_id} if turn_id else {}),
            }
            # The allowlist can change while an authenticated websocket stays
            # open. Reject the exact application turn before hydration,
            # transcript persistence, or an acceptance ACK; BaseChannel's
            # silent authorization return must not look like successful ingress.
            if not self.is_allowed(client_id):
                await self._send_event(
                    connection,
                    "error",
                    detail="access_denied",
                    **rejection_fields,
                )
                return
            if not isinstance(content, str):
                await self._send_event(
                    connection,
                    "error",
                    detail="missing content",
                    **rejection_fields,
                )
                return
            message_rejection = self._ingress.validate_text(content)
            if message_rejection is not None:
                await self._send_event(
                    connection,
                    "error",
                    detail="message_rejected",
                    reason=message_rejection,
                    **rejection_fields,
                )
                return

            try:
                temporary_policy = self._temporary_chats.message_policy(
                    connection,
                    cid,
                    content,
                )
            except TemporaryChatError as exc:
                await self._send_event(
                    connection,
                    "error",
                    detail=exc.detail,
                    **rejection_fields,
                )
                return

            raw_media = envelope.get("media")
            media_paths: list[str] = []
            media_names: list[str | None] = []
            if raw_media is not None:
                if not isinstance(raw_media, list):
                    await self._send_event(
                        connection,
                        "error",
                        detail="attachment_rejected",
                        reason="malformed",
                        **rejection_fields,
                    )
                    return
                media_paths, reason = self._media.store_inbound_attachments(cast(list[Any], raw_media))
                if reason is not None:
                    await self._send_event(
                        connection,
                        "error",
                        detail="attachment_rejected",
                        reason=reason,
                        **rejection_fields,
                    )
                    return
                for item in cast(list[Any], raw_media):
                    attachment = cast(dict[str, Any], item) if isinstance(item, dict) else {}
                    name = attachment.get("name")
                    media_names.append(
                        (safe_filename(name) or None) if isinstance(name, str) else None
                    )
                if temporary_policy is not None:
                    self._temporary_chats.register_media(connection, cid, media_paths)

            # Allow media-only turns (content may be empty when attachments are present).
            if not content.strip() and not media_paths:
                await self._send_event(
                    connection,
                    "error",
                    detail="missing content",
                    **rejection_fields,
                )
                return
            # Auto-attach on first use so clients can one-shot without a separate attach.
            self._attach(connection, cid)
            if temporary_policy is None or temporary_policy.hydrate_transcript:
                await self._hydrate_after_subscribe(cid)

            # Resolve after hydration so a concurrent downgrade cannot be overwritten.
            scope = await self._workspace_scope_or_error(
                connection,
                lambda: (
                    temporary_policy.workspace_scope
                    if temporary_policy is not None
                    else self._workspaces.scope_for_message(
                        envelope,
                        chat_id=cid,
                        chat_running=websocket_turn_wall_started_at(cid) is not None,
                        controls_available=self._workspace_controls_available(connection),
                    )
                ),
                chat_id=cid,
                turn_id=turn_id,
            )
            if scope is None:
                return

            # Hydration and scope resolution can yield. Re-check immediately
            # before transcript/bus mutation so a mid-flight revocation cannot
            # fall through BaseChannel's silent deny and still receive an ACK.
            if not self.is_allowed(client_id):
                await self._send_event(
                    connection,
                    "error",
                    detail="access_denied",
                    **rejection_fields,
                )
                return

            metadata: dict[str, Any] = {"remote": getattr(connection, "remote_address", None)}
            if envelope.get("webui") is True:
                metadata["webui"] = True
                metadata.update(self._transcripts.client_turn_metadata(envelope.get("turn_id")))
            trusted_webui = metadata.get("webui") is True and connection in self._webui_connections
            is_user_shell = (
                trusted_webui
                and envelope.get("user_shell") is True
                and content.startswith("!")
            )
            if is_user_shell:
                metadata[INBOUND_META_USER_SHELL] = True
            dispatch_content = (
                f"{USER_SHELL_COMMAND} {content[1:].lstrip()}"
                if is_user_shell
                else content
            )
            cli_apps = normalize_cli_app_mentions(envelope.get("cli_apps"))
            if cli_apps:
                metadata["cli_apps"] = cli_apps
            mcp_presets = normalize_mcp_preset_mentions(
                envelope.get("mcp_presets"),
                config_path=self.gateway.settings.config.path,
            )
            if mcp_presets:
                metadata["mcp_presets"] = mcp_presets
            session_mentions: list[SessionMention] = []
            if (
                trusted_webui
                and self._session_access is not None
            ):
                session_mentions = await asyncio.to_thread(
                    self._session_access.normalize_mentions,
                    envelope.get("session_mentions"),
                    exclude_session_key=f"{self.name}:{cid}",
                )
                if session_mentions:
                    metadata["session_mentions"] = session_mentions
            metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope.metadata()
            self._workspaces.persist_scope(cid, scope)
            is_webui = metadata.get("webui") is True
            queued_owner = None
            if is_webui and not is_user_shell and builtin_command_starts_agent_turn(content):
                queued_owner = register_queued_websocket_turn_if_idle(cid, turn_id)
                if queued_owner is not None:
                    metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] = queued_owner
            accepted = False
            try:
                if (
                    is_webui
                    and (
                        temporary_policy is None
                        or temporary_policy.persist_transcript
                    )
                ):
                    self._transcripts.append_user_message(
                        cid,
                        content,
                        metadata=metadata,
                        media_paths=media_paths or None,
                        cli_apps=cli_apps or None,
                        mcp_presets=mcp_presets or None,
                        session_mentions=session_mentions or None,
                    )
                if trusted_webui:
                    context_blocks: list[RuntimeContextBlock] = []
                    quote = webui_quote_runtime_context({
                        WEBUI_QUOTE_METADATA: envelope.get("quoted_context"),
                    })
                    if quote is not None:
                        context_blocks.append(quote)
                    session_context = session_mentions_runtime_context(session_mentions)
                    if session_context is not None:
                        context_blocks.append(session_context)
                    if context_blocks:
                        metadata[RUNTIME_CONTEXT_INPUT_META] = context_blocks
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=cid,
                    content=dispatch_content,
                    media=media_paths or None,
                    metadata=metadata,
                    is_dm=False,
                    session_key=(
                        temporary_policy.session_key
                        if temporary_policy is not None
                        else None
                    ),
                    require_existing_session=(
                        temporary_policy.require_existing_session
                        if temporary_policy is not None
                        else False
                    ),
                )
                accepted = True
            finally:
                if not accepted and queued_owner is not None:
                    clear_websocket_turn_if_current(cid, queued_owner)
            if is_webui:
                await self._broadcast_user_message(
                    connection,
                    cid,
                    content,
                    turn_id=turn_id,
                    starts_turn=queued_owner is not None,
                    media_paths=media_paths,
                    media_names=media_names,
                    cli_apps=cli_apps,
                    mcp_presets=mcp_presets,
                    session_mentions=session_mentions,
                )
            if is_webui and turn_id:
                active_turn_id = websocket_turn_id(cid)
                started_at = websocket_turn_wall_started_at(cid)
                await self._send_event(
                    connection,
                    "message_accepted",
                    chat_id=cid,
                    turn_id=turn_id,
                    starts_turn=queued_owner is not None,
                    **(
                        {"active_turn_id": active_turn_id}
                        if active_turn_id is not None
                        else {}
                    ),
                    **(
                        {"started_at": started_at}
                        if active_turn_id is not None and started_at is not None
                        else {}
                    ),
                )
            return
        await self._send_event(connection, "error", detail=f"unknown type: {t!r}")

    async def _start_webui_request(
        self,
        connection: ServerConnection,
        envelope: dict[str, Any],
    ) -> None:
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}",
            request_id,
        ) is None:
            await self._send_event(
                connection,
                "error",
                detail="invalid webui request_id",
            )
            return
        if connection not in self._webui_connections:
            await self._send_webui_response(
                connection,
                request_id,
                status=403,
                message="access_denied",
            )
            return

        action = envelope.get("action")
        payload = envelope.get("payload")
        if not isinstance(action, str) or re.fullmatch(
            r"[a-z][a-z0-9_.]{0,127}",
            action,
        ) is None:
            await self._send_webui_response(
                connection,
                request_id,
                status=400,
                message="invalid WebUI mutation action",
            )
            return
        if not isinstance(payload, dict):
            await self._send_webui_response(
                connection,
                request_id,
                status=400,
                message="WebUI mutation payload must be an object",
            )
            return

        payload_digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).digest()
        self._prune_webui_request_operations()
        operation = self._webui_request_operations.get(request_id)
        is_replay = operation is not None
        if operation is not None and (
            operation.action != action or operation.payload_digest != payload_digest
        ):
            await self._send_webui_response(
                connection,
                request_id,
                status=409,
                message="request_id was already used for a different WebUI mutation",
            )
            return
        if operation is None:
            operation_task = asyncio.create_task(
                self._execute_webui_request(
                    connection,
                    action,
                    cast(dict[str, Any], payload),
                )
            )
            new_operation = _WebUIRequestOperation(
                action=action,
                payload_digest=payload_digest,
                task=operation_task,
            )
            operation = new_operation
            self._webui_request_operations[request_id] = new_operation

            def mark_complete(_task: asyncio.Task[_WebUIRequestResult]) -> None:
                current = self._webui_request_operations.get(request_id)
                if current is not new_operation:
                    return
                new_operation.completed_at = time.monotonic()
                self._prune_webui_request_operations()

            operation_task.add_done_callback(mark_complete)

        key = (connection, request_id)
        if key in self._webui_request_tasks:
            return
        delivery_task = asyncio.create_task(
            self._deliver_webui_request(
                connection,
                request_id,
                operation.task,
                sequence=is_replay,
            )
        )
        self._webui_request_tasks[key] = delivery_task

    def _prune_webui_request_operations(self) -> None:
        now = time.monotonic()
        for request_id, operation in tuple(self._webui_request_operations.items()):
            if (
                operation.completed_at is not None
                and now - operation.completed_at >= _WEBUI_REQUEST_CACHE_TTL_S
            ):
                self._webui_request_operations.pop(request_id, None)

        completed = sorted(
            (
                (operation.completed_at, request_id)
                for request_id, operation in self._webui_request_operations.items()
                if operation.completed_at is not None
            ),
            key=lambda item: item[0],
        )
        for _, request_id in completed[:-_WEBUI_REQUEST_CACHE_MAX]:
            self._webui_request_operations.pop(request_id, None)

    def _discard_webui_request_lock_if_idle(self, connection: ServerConnection) -> None:
        if connection in self._webui_connections:
            return
        if any(task_connection is connection for task_connection, _ in self._webui_request_tasks):
            return
        self._webui_request_locks.pop(connection, None)

    async def _deliver_webui_request(
        self,
        connection: ServerConnection,
        request_id: str,
        operation_task: asyncio.Task[_WebUIRequestResult],
        *,
        sequence: bool = False,
    ) -> None:
        try:
            if sequence:
                # Make replayed work the predecessor for subsequent mutations on
                # this connection without blocking its receive loop.
                lock = self._webui_request_locks.setdefault(connection, asyncio.Lock())
                async with lock:
                    result = await asyncio.shield(operation_task)
                    await self._send_webui_response(
                        connection,
                        request_id,
                        result=result.result,
                        status=result.status,
                        message=result.message,
                    )
                return
            result = await asyncio.shield(operation_task)
            await self._send_webui_response(
                connection,
                request_id,
                result=result.result,
                status=result.status,
                message=result.message,
            )
        finally:
            self._webui_request_tasks.pop((connection, request_id), None)
            self._discard_webui_request_lock_if_idle(connection)

    async def _execute_webui_request(
        self,
        connection: ServerConnection,
        action: str,
        payload: dict[str, Any],
    ) -> _WebUIRequestResult:
        try:
            lock = self._webui_request_locks.setdefault(connection, asyncio.Lock())
            async with lock:
                response = await self._http_router.dispatch_webui_mutation(
                    connection,
                    action,
                    payload,
                )
                status = response.status_code
                body = bytes(response.body).decode("utf-8", errors="replace").strip()
                if 200 <= status < 300:
                    try:
                        result = json.loads(body)
                    except json.JSONDecodeError:
                        return _WebUIRequestResult(
                            status=502,
                            message="WebUI mutation returned an invalid response",
                        )
                    if action == "sidebar.update" and isinstance(result, dict):
                        await self._broadcast_webui_event(
                            "sidebar_state_updated",
                            state=result,
                        )
                    return _WebUIRequestResult(result=result)
                return _WebUIRequestResult(
                    status=status,
                    message=body or response.reason_phrase,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("WebUI mutation '{}' failed", action)
            return _WebUIRequestResult(
                status=500,
                message="WebUI mutation failed",
            )

    async def _send_webui_response(
        self,
        connection: ServerConnection,
        request_id: str,
        *,
        result: Any = None,
        status: int | None = None,
        message: str | None = None,
    ) -> None:
        if status is None:
            await self._send_event(
                connection,
                "webui_response",
                request_id=request_id,
                ok=True,
                result=result,
            )
            return
        await self._send_event(
            connection,
            "webui_response",
            request_id=request_id,
            ok=False,
            error={
                "status": status,
                "message": message or "WebUI mutation failed",
            },
        )

    async def _workspace_scope_or_error(
        self,
        connection: ServerConnection,
        resolver: Callable[[], Any],
        *,
        chat_id: str | None = None,
        turn_id: str | None = None,
    ) -> Any | None:
        try:
            return resolver()
        except WorkspaceScopeError as exc:
            await self._send_event(
                connection,
                "error",
                detail="workspace_scope_rejected",
                reason=exc.message,
                **({"chat_id": chat_id} if chat_id else {}),
                **({"turn_id": turn_id} if turn_id else {}),
            )
            return None

    # -- Outbound WebSocket events -----------------------------------------

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
                self.logger.debug("server task was already cancelled during shutdown")
            except Exception as e:
                self.logger.warning("server task error during shutdown: {}", e)
            self._server_task = None
        delivery_tasks = tuple(self._webui_request_tasks.values())
        operation_tasks = tuple(
            operation.task for operation in self._webui_request_operations.values()
        )
        for task in (*delivery_tasks, *operation_tasks):
            task.cancel()
        if delivery_tasks:
            await asyncio.gather(*delivery_tasks, return_exceptions=True)
        if operation_tasks:
            await asyncio.gather(*operation_tasks, return_exceptions=True)
        self._webui_request_tasks.clear()
        self._webui_request_locks.clear()
        self._webui_request_operations.clear()
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()
        self._webui_connections.clear()
        self._tokens.clear()
        self._temporary_chats.close()

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
        if (
            not persisted
            and phase in {"answer", "complete"}
            and (metadata or {}).get("webui") is True
        ):
            owner = (metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            mark_websocket_turn_transcript_persistence_failed(
                chat_id,
                owner if isinstance(owner, str) else None,
            )
        return persisted

    async def send(self, msg: OutboundMessage) -> None:
        event = outbound_event_from_message(msg)
        progress_event = event if isinstance(event, ProgressEvent) else None
        if isinstance(event, RuntimeModelUpdatedEvent):
            await self.send_runtime_model_updated(
                model_name=event.model,
                model_preset=event.model_preset,
            )
            return

        # Snapshot the subscriber set so ConnectionClosed cleanups mid-iteration are safe.
        conns = list(self._subs.get(msg.chat_id, ()))
        if not conns:
            if isinstance(
                event,
                ProgressEvent
                | UserInputEvent
                | TurnEndEvent
                | SessionUpdatedEvent
                | GoalStatusEvent
                | GoalStateSyncEvent,
            ):
                self.logger.debug("no active subscribers for chat_id={}", msg.chat_id)
            else:
                self.logger.warning("no active subscribers for chat_id={}", msg.chat_id)
        if isinstance(event, TurnModelUpdatedEvent):
            if conns:
                await self.send_turn_model_updated(
                    msg.chat_id,
                    model_name=event.model,
                    model_preset=event.model_preset,
                    context_window_tokens=event.context_window_tokens,
                )
            return
        if isinstance(event, UserInputEvent):
            if conns:
                await self.send_user_input(
                    msg.chat_id,
                    content=event.content,
                    created_at_ms=event.created_at_ms,
                    provenance=event.provenance,
                )
            return
        if isinstance(event, GoalStateSyncEvent):
            if conns:
                await self.send_goal_state(msg.chat_id, event.goal_state or {"active": False})
            return
        if isinstance(event, GoalStatusEvent):
            turn_id = (msg.metadata or {}).get(WEBUI_TURN_METADATA_KEY)
            current_turn_id = turn_id if isinstance(turn_id, str) else None
            turn_owner = (msg.metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            current_turn_owner = turn_owner if isinstance(turn_owner, str) else None
            try:
                if conns and event.status in ("running", "idle"):
                    await self.send_goal_status(
                        msg.chat_id,
                        event.status,
                        started_at=event.started_at,
                        turn_id=current_turn_id,
                    )
            finally:
                if event.status == "idle":
                    # Cancellation/direct runs may have no turn_end, so idle is
                    # still terminal. A failed canonical completion write is
                    # the one case that must remain pending for safe resume.
                    clear_websocket_turn_if_current(
                        msg.chat_id,
                        current_turn_owner,
                        preserve_persistence_failure=True,
                    )
            return
        # Signal that the agent has fully finished processing the current turn.
        if isinstance(event, TurnEndEvent):
            turn_id = (msg.metadata or {}).get(WEBUI_TURN_METADATA_KEY)
            session_update_scope = (
                "metadata"
                if isinstance(turn_id, str)
                and turn_id.startswith(WEBUI_SYSTEM_COMMAND_TURN_PREFIX)
                else "thread"
            )
            turn_owner = (msg.metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            await self.send_turn_end(
                msg.chat_id,
                latency_ms=event.latency_ms,
                goal_state=event.goal_state,
                usage=event.usage,
                context_window_tokens=event.context_window_tokens,
                metadata=msg.metadata,
                turn_owner=turn_owner if isinstance(turn_owner, str) else None,
            )
            await self.send_session_updated(msg.chat_id, scope=session_update_scope)
            return
        if isinstance(event, SessionUpdatedEvent):
            if conns:
                await self.send_session_updated(
                    msg.chat_id,
                    scope=event.scope,
                )
            return
        if progress_event and progress_event.file_edit_events:
            await self.send_file_edit_events(
                msg.chat_id,
                progress_event.file_edit_events,
                msg.metadata,
            )
            return
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
        self._persist_turn_transcript_event(
            chat_id,
            body,
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
        self._persist_turn_transcript_event(
            chat_id,
            body,
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
        self._persist_turn_transcript_event(
            chat_id,
            body,
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
        usage: dict[str, int] | None = None,
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
        if usage:
            body["usage"] = usage
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
        raw = json.dumps(body, ensure_ascii=False)
        if not conns:
            return
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_end ")

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
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_model_updated ")
