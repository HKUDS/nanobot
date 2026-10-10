"""Authenticated network access settings and saved versus active listener scope."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypedDict
from urllib.parse import urlsplit

from nanobot.config.loader import resolve_config_env_vars
from nanobot.config.schema import Config
from nanobot.webui.http_utils import (
    case_insensitive_header,
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
    password_required: bool


def browser_origin_allowed(headers: Any, *, public_ws_url: str = "") -> bool:
    """Allow same-origin browsers and the loopback-only development client.

    Non-browser clients may omit Origin. Authentication is checked separately.
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
            "password_required": self._password_required(saved),
        }

    @staticmethod
    def _password_required(config: WebSocketConfig) -> bool:
        return not (config.token.strip() or config.trusted_proxy_auth) and (
            config.token_issue_secret_generated or not config.token_issue_secret.strip()
        )

    def update_scope(
        self, allow_other_devices: object, password: object = None, *, local_browser: bool,
    ) -> None:
        if type(allow_other_devices) is not bool:
            raise WebUIAccessError("invalid_access_scope")
        if password is not None:
            if (not allow_other_devices or not isinstance(password, str)
                    or not re.fullmatch(r"[\x21-\x7e]{8,1024}", password)
                    or not re.search(r"[a-z]", password)
                    or not re.search(r"[A-Z]", password)
                    or not re.search(r"[0-9]", password)
                    or not re.search(r"[^A-Za-z0-9]", password)
                    or "${" in password):
                raise WebUIAccessError("invalid_password")
            if not local_browser:
                raise WebUIAccessError("access_local_only", 403)

        def update(config: Config) -> str | None:
            websocket = self._websocket(config)
            if websocket.unix_socket_path or self.active.unix_socket_path:
                raise WebUIAccessError("unix_socket_access_scope", 409)
            needs_password = self._password_required(websocket)
            # Recheck under the config-file lock: another tab may have set the password.
            if password is not None and not needs_password:
                raise WebUIAccessError("password_already_set", 409)
            if allow_other_devices and needs_password and password is None:
                raise WebUIAccessError("password_required")
            saved: dict[str, Any] = dict(getattr(config.channels, "websocket", {}) or {})
            if isinstance(password, str):
                for key in ("token_issue_secret", "token_issue_secret_generated", "websocket_requires_token"):
                    saved.pop(key, None)
                saved.update(
                    tokenIssueSecret=password, tokenIssueSecretGenerated=False,
                    websocketRequiresToken=True,
                )
            if allow_other_devices != (not is_loopback_host(websocket.host)):
                saved["host"] = "0.0.0.0" if allow_other_devices else "127.0.0.1"
            setattr(config.channels, "websocket", saved)
            return password if isinstance(password, str) else None

        saved_password = self.config.update(update)
        if saved_password is not None:
            # Existing local sessions finish normally; restart clears them before
            # opening the external listener. New logins already use the new password.
            self.active.token_issue_secret = saved_password
            self.active.token_issue_secret_generated = False
            self.active.websocket_requires_token = True
