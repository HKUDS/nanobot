"""HTTP API handler extracted from WebSocketChannel.

Handles all non-WebSocket HTTP routes: bootstrap, sessions, settings,
media, commands, sidebar state, static file serving, and token management.

Also houses shared HTTP utility functions used by both this module and
``websocket.py`` to avoid circular imports.
"""

from __future__ import annotations

import email.utils
import hmac
import http
import json
import mimetypes
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from loguru import logger
from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.command.builtin import builtin_command_palette
from nanobot.config.paths import get_media_dir
from nanobot.utils.subagent_channel_display import scrub_subagent_messages_for_channel
from nanobot.webui.media_api import (
    serve_signed_media,
    sign_media_path,
    sign_or_stage_media_path,
)
from nanobot.webui.sidebar_state import (
    read_webui_sidebar_state,
    write_webui_sidebar_state,
)
from nanobot.webui.thread_disk import delete_webui_thread
from nanobot.webui.transcript import (
    build_webui_thread_response,
    rewrite_local_markdown_images,
)

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import SessionManager


# ---------------------------------------------------------------------------
# Shared HTTP utility functions (imported by websocket.py)
# ---------------------------------------------------------------------------


def _strip_trailing_slash(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path or "/"


def _normalize_config_path(path: str) -> str:
    return _strip_trailing_slash(path)


def _case_insensitive_header(headers: Any, key: str) -> str:
    """Read a header from websockets/http test stubs without assuming casing."""
    try:
        value = headers.get(key)
    except Exception:
        value = None
    if value is None:
        try:
            value = headers.get(key.lower())
        except Exception:
            value = None
    return str(value or "").strip()


def _safe_host_header(value: str) -> str:
    """Return a safe Host header value, or empty when it should not be echoed."""
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"\[[0-9A-Fa-f:.]+\](?::\d{1,5})?", value):
        return value
    if re.fullmatch(r"[A-Za-z0-9.-]+(?::\d{1,5})?", value):
        return value
    return ""


def _host_for_url(host: str, port: int) -> str:
    host = host.strip()
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


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


def _http_response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
    extra_headers: list[tuple[str, str]] | None = None,
) -> Response:
    headers = [
        ("Date", email.utils.formatdate(usegmt=True)),
        ("Connection", "close"),
        ("Content-Length", str(len(body))),
        ("Content-Type", content_type),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, Headers(headers), body)


def _http_error(status: int, message: str | None = None) -> Response:
    body = (message or http.HTTPStatus(status).phrase).encode("utf-8")
    return _http_response(body, status=status)


def _parse_request_path(path_with_query: str) -> tuple[str, dict[str, list[str]]]:
    """Parse normalized path and query parameters in one pass."""
    parsed = urlparse("ws://x" + path_with_query)
    path = _strip_trailing_slash(parsed.path or "/")
    return path, parse_qs(parsed.query, keep_blank_values=True)


def _normalize_http_path(path_with_query: str) -> str:
    return _parse_request_path(path_with_query)[0]


def _parse_query(path_with_query: str) -> dict[str, list[str]]:
    return _parse_request_path(path_with_query)[1]


def _query_first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _is_localhost(connection: Any) -> bool:
    addr = getattr(connection, "remote_address", None)
    if not addr:
        return False
    host = addr[0] if isinstance(addr, tuple) else addr
    if not isinstance(host, str):
        return False
    if host.startswith("::ffff:"):
        host = host[7:]
    return host in {"127.0.0.1", "::1", "localhost"}


def _bearer_token(headers: Any) -> str | None:
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _issue_route_secret_matches(headers: Any, configured_secret: str) -> bool:
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


def _decode_api_key(raw_key: str) -> str | None:
    from urllib.parse import unquote

    key = unquote(raw_key)
    _api_key_re = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")
    if _api_key_re.match(key) is None:
        return None
    return key


def _default_model_name_from_config() -> str | None:
    try:
        from nanobot.config.loader import load_config
        model = load_config().resolve_preset().model.strip()
        return model or None
    except Exception as e:
        logger.debug("bootstrap model_name could not load from config: {}", e)
        return None


def _resolve_bootstrap_model_name(
    runtime_name: Callable[[], str | None] | None,
) -> str | None:
    if runtime_name is not None:
        try:
            raw = runtime_name()
        except Exception as e:
            logger.debug("bootstrap runtime model resolver failed: {}", e)
        else:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped:
                    return stripped
    return _default_model_name_from_config()


# ---------------------------------------------------------------------------
# GatewayHTTPHandler
# ---------------------------------------------------------------------------


class GatewayHTTPHandler:
    """Handles all HTTP routes served alongside the WebSocket endpoint.

    Owns token management, session API, media API, static file serving,
    and delegates settings routes to ``WebUISettingsRouter``.
    """

    _MAX_ISSUED_TOKENS = 10_000

    def __init__(
        self,
        *,
        config: Any,  # WebSocketConfig
        session_manager: SessionManager | None,
        static_dist_path: Path | None,
        workspace_path: Path,
        runtime_model_name: Callable[[], str | None] | None,
        runtime_surface: str,
        runtime_capabilities_overrides: dict[str, Any] | None,
        bus: MessageBus,
        log: Any = logger,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.static_dist_path = static_dist_path
        self.workspace_path = workspace_path
        self.runtime_model_name = runtime_model_name
        self.bus = bus
        self._log = log
        self._runtime_surface = runtime_surface

        self.issued_tokens: dict[str, float] = {}
        self.api_tokens: dict[str, float] = {}
        self.media_secret: bytes = secrets.token_bytes(32)

        # Workspace controller
        from nanobot.webui.workspaces import WebUIWorkspaceController

        self.workspaces = WebUIWorkspaceController(
            session_manager=session_manager,
            default_workspace=workspace_path,
            default_restrict_to_workspace=None,
        )

        # Settings router
        from nanobot.webui.settings_api import runtime_capabilities as _rc
        from nanobot.webui.settings_routes import WebUISettingsRouter

        self._capabilities = _rc(runtime_surface, runtime_capabilities_overrides or {})
        self.settings_routes = WebUISettingsRouter(
            bus=bus,
            logger=self._log,
            check_api_token=self.check_api_token,
            parse_query=_parse_query,
            json_response=_http_json_response,
            error_response=_http_error,
            runtime_surface=runtime_surface,
            runtime_capabilities=self._capabilities,
        )

    # -- Token management ---------------------------------------------------

    def check_api_token(self, request: WsRequest) -> bool:
        self._purge_expired_api_tokens()
        token = _bearer_token(request.headers) or _query_first(
            _parse_query(request.path), "token"
        )
        if not token:
            return False
        expiry = self.api_tokens.get(token)
        if expiry is None or time.monotonic() > expiry:
            self.api_tokens.pop(token, None)
            return False
        return True

    def _purge_expired_api_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self.api_tokens.items()):
            if now > expiry:
                self.api_tokens.pop(token_key, None)

    def _purge_expired_issued_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self.issued_tokens.items()):
            if now > expiry:
                self.issued_tokens.pop(token_key, None)

    def take_issued_token_if_valid(self, token_value: str | None) -> bool:
        if not token_value:
            return False
        self._purge_expired_issued_tokens()
        expiry = self.issued_tokens.pop(token_value, None)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            return False
        return True

    # -- Main dispatch ------------------------------------------------------

    async def dispatch(self, connection: Any, request: WsRequest) -> Any | None:
        """Route an HTTP request. Returns Response or None."""
        got, query = _parse_request_path(request.path)

        # Token issue endpoint
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue(connection, request)

        # Bootstrap
        if got == "/webui/bootstrap":
            return self._handle_bootstrap(connection, request)

        # Settings routes (delegated)
        response = await self.settings_routes.dispatch(request, got)
        if response is not None:
            return response

        # Session routes
        response = self._dispatch_session_routes(request, got)
        if response is not None:
            return response

        # Media routes
        response = self._dispatch_media_routes(request, got)
        if response is not None:
            return response

        # Misc routes
        response = self._dispatch_misc_routes(connection, request, got)
        if response is not None:
            return response

        # API 404 (never serve SPA for /api/ routes)
        if got.startswith("/api/"):
            return _http_error(404, "API route not found")

        # Static SPA serving
        if self.static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    # -- Token issue --------------------------------------------------------

    def _handle_token_issue(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self._log.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        self._purge_expired_issued_tokens()
        if len(self.issued_tokens) >= self._MAX_ISSUED_TOKENS:
            self._log.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self.issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = f"nbwt_{secrets.token_urlsafe(32)}"
        self.issued_tokens[token_value] = time.monotonic() + float(self.config.token_ttl_s)
        return _http_json_response(
            {"token": token_value, "expires_in": self.config.token_ttl_s}
        )

    # -- Bootstrap ----------------------------------------------------------

    def _handle_bootstrap(self, connection: Any, request: Any) -> Response:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return _http_error(401, "Unauthorized")
        elif not _is_localhost(connection):
            return _http_error(403, "bootstrap is localhost-only")

        self._purge_expired_issued_tokens()
        self._purge_expired_api_tokens()
        if (
            len(self.issued_tokens) >= self._MAX_ISSUED_TOKENS
            or len(self.api_tokens) >= self._MAX_ISSUED_TOKENS
        ):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
            )
        token = f"nbwt_{secrets.token_urlsafe(32)}"
        expiry = time.monotonic() + float(self.config.token_ttl_s)
        self.issued_tokens[token] = expiry
        self.api_tokens[token] = expiry

        ws_url = self._bootstrap_ws_url(request)
        expected_path = _normalize_config_path(self.config.path)
        return _http_json_response(
            {
                "token": token,
                "ws_path": expected_path,
                "ws_url": ws_url,
                "expires_in": self.config.token_ttl_s,
                "model_name": _resolve_bootstrap_model_name(self.runtime_model_name),
                "runtime_surface": self._runtime_surface,
                "runtime_capabilities": self._capabilities,
            }
        )

    def _bootstrap_ws_url(self, request: Any) -> str:
        headers = getattr(request, "headers", {}) or {}
        host = _safe_host_header(_case_insensitive_header(headers, "Host"))
        if not host:
            host = _host_for_url(self.config.host, self.config.port)
        proto = _case_insensitive_header(headers, "X-Forwarded-Proto")
        proto = proto.split(",", 1)[0].strip().lower()
        secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())
        scheme = "wss" if secure else "ws"
        expected_path = _normalize_config_path(self.config.path)
        return f"{scheme}://{host}{expected_path}"

    # -- Session routes -----------------------------------------------------

    def _dispatch_session_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return self._handle_session_messages(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/webui-thread$", got)
        if m:
            return self._handle_webui_thread_get(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return self._handle_session_delete(request, m.group(1))

        return None

    def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        sessions = self.session_manager.list_sessions()
        from nanobot.session.webui_turns import websocket_turn_wall_started_at

        cleaned = []
        for s in sessions:
            key = s.get("key")
            if not (isinstance(key, str) and key.startswith("websocket:")):
                continue
            row = {k: v for k, v in s.items() if k != "path"}
            chat_id = key.split(":", 1)[1]
            started_at = websocket_turn_wall_started_at(chat_id)
            if started_at is not None:
                row["run_started_at"] = started_at
            scope = self.workspaces.scope_for_session_key(key)
            row["workspace_scope"] = scope.payload()
            cleaned.append(row)
        return _http_json_response({"sessions": cleaned})

    def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = self.session_manager.read_session_file(decoded_key)
        if data is None:
            return _http_error(404, "session not found")
        messages = data.get("messages")
        if isinstance(messages, list):
            scrub_subagent_messages_for_channel(messages)
        self._augment_media_urls(data)
        return _http_json_response(data)

    def _handle_webui_thread_get(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        scope = self.workspaces.scope_for_session_key(decoded_key)
        data = build_webui_thread_response(
            decoded_key,
            augment_user_media=self._augment_transcript_user_media,
            augment_assistant_text=lambda text: rewrite_local_markdown_images(
                text,
                workspace_path=scope.project_path,
                sign_path=self.sign_or_stage_media_path,
            ),
        )
        if data is None:
            return _http_error(404, "webui thread not found")
        data["workspace_scope"] = scope.payload()
        return _http_json_response(data)

    def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        deleted = self.session_manager.delete_session(decoded_key)
        delete_webui_thread(decoded_key)
        return _http_json_response({"deleted": bool(deleted)})

    # -- Media routes -------------------------------------------------------

    def _dispatch_media_routes(self, request: WsRequest, got: str) -> Response | None:
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2), request)
        return None

    def _handle_media_fetch(
        self, sig: str, payload: str, request: WsRequest | None = None
    ) -> Response:
        return serve_signed_media(
            sig,
            payload,
            secret=self.media_secret,
            request=request,
            media_dir=lambda channel=None: get_media_dir(channel),
        )

    def sign_media_path(self, abs_path: Path) -> str | None:
        return sign_media_path(
            abs_path,
            secret=self.media_secret,
            media_dir=lambda channel=None: get_media_dir(channel),
        )

    def sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        return sign_or_stage_media_path(
            path,
            secret=self.media_secret,
            media_dir=lambda channel=None: get_media_dir(channel),
            logger=self._log,
        )

    def rewrite_local_markdown_images(self, text: str) -> str:
        return rewrite_local_markdown_images(
            text,
            workspace_path=self.workspace_path,
            sign_path=self.sign_or_stage_media_path,
        )

    # -- Misc routes --------------------------------------------------------

    def _dispatch_misc_routes(
        self, connection: Any, request: WsRequest, got: str
    ) -> Response | None:
        if got == "/api/sessions":
            return self._handle_sessions_list(request)
        if got == "/api/commands":
            return self._handle_commands(request)
        if got == "/api/workspaces":
            return self._handle_workspaces(connection, request)
        if got == "/api/webui/sidebar-state":
            return self._handle_webui_sidebar_state(request)
        if got == "/api/webui/sidebar-state/update":
            return self._handle_webui_sidebar_state_update(request)
        return None

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_workspaces(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            self.workspaces.payload(controls_available=_is_localhost(connection))
        )

    def _handle_webui_sidebar_state(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(read_webui_sidebar_state())

    def _handle_webui_sidebar_state_update(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        query = _parse_query(request.path)
        raw_state = _query_first(query, "state")
        if raw_state is None:
            return _http_error(400, "missing state")
        try:
            decoded = json.loads(raw_state)
        except json.JSONDecodeError:
            return _http_error(400, "state must be JSON")
        if not isinstance(decoded, dict):
            return _http_error(400, "state must be an object")
        try:
            state = write_webui_sidebar_state(decoded)
        except ValueError as e:
            return _http_error(400, str(e))
        except OSError:
            self._log.exception("failed to write webui sidebar state")
            return _http_error(500, "failed to write sidebar state")
        return _http_json_response(state)

    # -- Static file serving ------------------------------------------------

    def _serve_static(self, request_path: str) -> Response | None:
        assert self.static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self.static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self.static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            index = self.static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            self._log.warning("static: failed to read {}: {}", candidate, e)
            return _http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )

    # -- Media helpers (called by WebSocketChannel.send) --------------------

    def _augment_media_urls(self, payload: dict[str, Any]) -> None:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            media = msg.get("media")
            if not isinstance(media, list) or not media:
                continue
            urls: list[dict[str, str]] = []
            for entry in media:
                if not isinstance(entry, str) or not entry:
                    continue
                signed = self.sign_media_path(Path(entry))
                if signed is None:
                    continue
                urls.append({"url": signed, "name": Path(entry).name})
            if urls:
                msg["media_urls"] = urls
            msg.pop("media", None)

    def _augment_transcript_user_media(self, paths: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pstr in paths:
            path = Path(pstr)
            att = self.sign_or_stage_media_path(path)
            if att is None:
                continue
            mime, _ = mimetypes.guess_type(path.name)
            kind = "video" if mime and mime.startswith("video/") else "image"
            out.append(
                {"kind": kind, "url": att["url"], "name": att.get("name", path.name)},
            )
        return out


def _is_websocket_channel_session_key(key: str) -> bool:
    return key.startswith("websocket:")
