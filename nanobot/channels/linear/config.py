"""Configuration and URL validation for the native Linear channel."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from nanobot.config_base import Base

DEFAULT_PORT = 3979
DEFAULT_WEBHOOK_PATH = "/linear/webhook"
DEFAULT_OAUTH_CALLBACK_PATH = "/linear/oauth/callback"


class LinearConfig(Base):
    """Linear OAuth app and local webhook listener settings."""

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    webhook_signing_secret: str = ""
    public_base_url: str = ""
    host: str = "0.0.0.0"
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    webhook_path: str = DEFAULT_WEBHOOK_PATH
    oauth_callback_path: str = DEFAULT_OAUTH_CALLBACK_PATH
    allow_from: list[str] = Field(default_factory=list)
    send_progress: bool = True
    send_tool_hints: bool = True
    show_reasoning: bool = True

    @field_validator("webhook_path", "oauth_callback_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = value.strip()
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("must be an absolute URL path without a query or fragment")
        return path.rstrip("/") or "/"

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str) -> str:
        raw = value.strip()
        return validate_public_base_url(raw) if raw else ""

    @model_validator(mode="after")
    def validate_distinct_paths(self) -> LinearConfig:
        if self.webhook_path == self.oauth_callback_path:
            raise ValueError("Linear webhookPath and oauthCallbackPath must be different")
        return self

    def validate_runtime(self) -> None:
        missing = [
            label
            for label, value in (
                ("clientId", self.client_id),
                ("clientSecret", self.client_secret),
                ("webhookSigningSecret", self.webhook_signing_secret),
                ("publicBaseUrl", self.public_base_url),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError("Missing Linear setting(s): " + ", ".join(missing))

    @property
    def redirect_uri(self) -> str:
        return self.public_base_url.rstrip("/") + self.oauth_callback_path

    @property
    def webhook_url(self) -> str:
        return self.public_base_url.rstrip("/") + self.webhook_path


def validate_public_base_url(value: str) -> str:
    """Require the externally reachable HTTPS origin Linear expects."""
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("publicBaseUrl must be an HTTPS origin, for example https://bot.example.com")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("publicBaseUrl must not include a path, query, or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("publicBaseUrl contains an invalid port") from exc
    if parsed.netloc.endswith(":") or any(character.isspace() for character in parsed.netloc):
        raise ValueError("publicBaseUrl contains an invalid host or port")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("publicBaseUrl must be public; localhost is not accepted by Linear")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("publicBaseUrl must not use a private or loopback IP address")
    return raw.rstrip("/")
