"""First-run authentication and saved versus active WebUI listener scope."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TypedDict, cast
from urllib.parse import urlsplit

from aiohttp import web

from nanobot.config.loader import resolve_config_env_vars
from nanobot.config.schema import Config
from nanobot.webui.http_utils import (
    case_insensitive_header,
    is_local_browser_request,
    is_loopback_host,
)
from nanobot.webui.settings_services import WebUISettingsConfig

if TYPE_CHECKING:
    from nanobot.channels.websocket.runtime import WebSocketConfig


class WebUIAccessError(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class WebUIAccessPayload(TypedDict):
    allow_other_devices: bool
    active_allow_other_devices: bool
    host: str
    active_host: str
    requires_restart: bool
    can_change: bool


def browser_origin_allowed(headers: Any, *, public_ws_url: str = "") -> bool:
    """Allow same-origin browsers and the loopback-only development client.

    Non-browser clients may omit Origin. First-run writes require it separately.
    Forwarded headers never establish permission to initialize an instance.
    """
    origin = case_insensitive_header(headers, "Origin")
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.path or parsed.query
                or parsed.fragment):
            return False
        host = case_insensitive_header(headers, "Host")
        return (
            parsed.netloc.lower() == host.lower()
            or bool(public_ws_url and parsed.netloc == urlsplit(public_ws_url).netloc)
            or (is_loopback_host(parsed.hostname or "") and is_loopback_host(host))
        )
    except ValueError:
        return False


class WebUIAccess:
    def __init__(self, active: WebSocketConfig, config: WebUISettingsConfig) -> None:
        self.active = active
        self.config = config
        self._setup_lock = asyncio.Lock()

    @property
    def setup_required(self) -> bool:
        return not self.active.has_access_auth

    def _websocket(self, config: Config) -> WebSocketConfig:
        from nanobot.channels.websocket.runtime import WebSocketConfig

        resolved = resolve_config_env_vars(config.model_copy(deep=True), config_path=self.config.path)
        return WebSocketConfig.model_validate(getattr(resolved.channels, "websocket", {}) or {})

    def payload(self) -> WebUIAccessPayload:
        saved = self._websocket(self.config.load())
        return {
            "allow_other_devices": not saved.unix_socket_path and not is_loopback_host(saved.host),
            "active_allow_other_devices": (
                not self.active.unix_socket_path and not is_loopback_host(self.active.host)
            ),
            "host": saved.unix_socket_path or saved.host,
            "active_host": self.active.unix_socket_path or self.active.host,
            "requires_restart": (saved.host, saved.unix_socket_path) != (
                self.active.host, self.active.unix_socket_path,
            ),
            "can_change": not (saved.unix_socket_path or self.active.unix_socket_path),
        }

    def update_scope(self, allow_other_devices: object) -> None:
        if type(allow_other_devices) is not bool:
            raise WebUIAccessError("invalid_access_scope")
        if self.setup_required:
            raise WebUIAccessError("setup_required", 428)

        def update(config: Config) -> None:
            websocket = self._websocket(config)
            if not websocket.has_access_auth:
                raise WebUIAccessError("setup_required", 428)
            if websocket.unix_socket_path or self.active.unix_socket_path:
                raise WebUIAccessError("unix_socket_access_scope", 409)
            if allow_other_devices != (not is_loopback_host(websocket.host)):
                saved: dict[str, Any] = dict(getattr(config.channels, "websocket", {}) or {})
                saved["host"] = "0.0.0.0" if allow_other_devices else "127.0.0.1"
                setattr(config.channels, "websocket", saved)

        self.config.update(update)

    async def handle_setup(self, request: web.BaseRequest) -> web.Response:
        """Accept one bounded local JSON write before normal credentials exist."""
        try:
            if request.method != "POST":
                raise WebUIAccessError("method_not_allowed", 405)
            peer = request.transport.get_extra_info("peername") if request.transport else None
            connection = SimpleNamespace(remote_address=peer)
            origin = request.headers.get("Origin", "")
            if (self.active.unix_socket_path or not is_loopback_host(self.active.host)
                    or not is_local_browser_request(connection, request.headers)
                    or not origin or not browser_origin_allowed(request.headers)):
                raise WebUIAccessError("setup_local_only", 403)
            if not self.setup_required:
                raise WebUIAccessError("already_initialized", 409)
            if (request.content_type != "application/json"
                    or request.headers.get("Content-Encoding")
                    or request.headers.get("Transfer-Encoding")
                    or not 0 < (request.content_length or 0) <= 16_384):
                raise WebUIAccessError("invalid_request")
            try:
                body: object = json.loads(await asyncio.wait_for(request.read(), timeout=10))
            except (ValueError, TimeoutError):
                raise WebUIAccessError("invalid_request") from None
            password = cast(dict[str, object], body).get("password") if isinstance(body, dict) else None
            if (not isinstance(password, str) or not 1 <= len(password.strip()) <= 1024
                    or "${" in password):
                raise WebUIAccessError("invalid_password")
            password = password.strip()

            def initialize(config: Config) -> None:
                saved = self._websocket(config)
                # The file lock covers this check and the atomic config replacement.
                if saved.has_access_auth:
                    raise WebUIAccessError("already_initialized", 409)
                values: dict[str, Any] = dict(getattr(config.channels, "websocket", {}) or {})
                values.pop("token_issue_secret", None)
                values.pop("websocket_requires_token", None)
                values.update(tokenIssueSecret=password, websocketRequiresToken=True)
                setattr(config.channels, "websocket", values)

            async with self._setup_lock:
                if not self.setup_required:
                    raise WebUIAccessError("already_initialized", 409)
                await asyncio.to_thread(self.config.update, initialize)
                # A failed save must leave the running gateway uninitialized.
                self.active.token_issue_secret = password
                self.active.websocket_requires_token = True
            response = web.json_response({"ok": True})
        except WebUIAccessError as exc:
            response = web.json_response({"error": exc.code}, status=exc.status)
        except (OSError, ValueError):
            response = web.json_response({"error": "save_failed"}, status=500)
        response.headers["Cache-Control"] = "no-store"
        response.force_close()
        return response
