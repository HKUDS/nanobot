"""Shared OAuth provider status and expiry helpers."""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.providers.registry import PROVIDERS, ProviderSpec, find_by_name

DAY_MS = 24 * 60 * 60 * 1000
CLI_EXPIRY_WARNING_DAYS = 7
RUNTIME_EXPIRY_WARNING_DAYS = 1


@dataclass(frozen=True)
class OAuthProviderStatus:
    configured: bool
    account: str | None
    expires_at: int | None
    login_supported: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "account": self.account,
            "expires_at": self.expires_at,
            "login_supported": self.login_supported,
        }


class OAuthRuntimeWarningTracker:
    """Log one-time runtime warnings for user-facing OAuth surfaces."""

    def __init__(self, *, threshold_days: int = RUNTIME_EXPIRY_WARNING_DAYS) -> None:
        self.threshold_days = threshold_days
        self._logged: set[tuple[str, int | None]] = set()

    def warn_for_provider(self, provider_name: str | None) -> str | None:
        if not provider_name:
            return None
        spec = find_by_name(provider_name.replace("-", "_"))
        if spec is None or not spec.is_oauth:
            return None

        status = get_oauth_provider_status(spec)
        warning = oauth_expiry_warning(
            spec,
            status,
            threshold_days=self.threshold_days,
        )
        if not warning:
            return None

        key = (spec.name, status.expires_at)
        if key in self._logged:
            return None
        self._logged.add(key)
        logger.warning(warning)
        return warning


def oauth_provider_specs() -> tuple[ProviderSpec, ...]:
    return tuple(spec for spec in PROVIDERS if spec.is_oauth)


def get_oauth_provider_status(spec: ProviderSpec | Any) -> OAuthProviderStatus:
    if not getattr(spec, "is_oauth", False):
        return OAuthProviderStatus(False, None, None, False)

    if spec.name == "openai_codex":
        return _openai_codex_status()

    if spec.name == "github_copilot":
        return _github_copilot_status()

    return OAuthProviderStatus(False, None, None, False)


def get_oauth_provider_status_by_name(provider_name: str | None) -> OAuthProviderStatus | None:
    if not provider_name:
        return None
    spec = find_by_name(provider_name.replace("-", "_"))
    if spec is None or not spec.is_oauth:
        return None
    return get_oauth_provider_status(spec)


def oauth_expires_soon(
    status: OAuthProviderStatus,
    *,
    threshold_days: int = CLI_EXPIRY_WARNING_DAYS,
    now_ms: int | None = None,
) -> bool:
    if not status.configured or status.expires_at is None:
        return False
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return status.expires_at <= now_ms + threshold_days * DAY_MS


def oauth_expiry_warning(
    spec: ProviderSpec,
    status: OAuthProviderStatus,
    *,
    threshold_days: int = CLI_EXPIRY_WARNING_DAYS,
    now_ms: int | None = None,
) -> str | None:
    if not oauth_expires_soon(status, threshold_days=threshold_days, now_ms=now_ms):
        return None
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    remaining_ms = max(0, int(status.expires_at or 0) - now_ms)
    return (
        f"{spec.label} OAuth token expires {format_oauth_expiry_delta(remaining_ms)}. "
        f"Run: nanobot provider login {spec.name.replace('_', '-')}"
    )


def format_oauth_expiry_delta(remaining_ms: int) -> str:
    if remaining_ms <= 0:
        return "now"
    hours = max(1, int((remaining_ms + 60 * 60 * 1000 - 1) // (60 * 60 * 1000)))
    if hours < 48:
        unit = "hour" if hours == 1 else "hours"
        return f"in {hours} {unit}"
    days = max(1, int((remaining_ms + DAY_MS - 1) // DAY_MS))
    unit = "day" if days == 1 else "days"
    return f"in {days} {unit}"


def _openai_codex_status() -> OAuthProviderStatus:
    try:
        from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
        from oauth_cli_kit.storage import FileTokenStorage
    except Exception:
        return OAuthProviderStatus(False, None, None, False)

    token = None
    with suppress(Exception):
        token = FileTokenStorage(
            token_filename=OPENAI_CODEX_PROVIDER.token_filename,
        ).load()
    expires_at = _coerce_expires_ms(getattr(token, "expires", None)) if token else None
    now_ms = int(time.time() * 1000)
    configured = bool(
        token
        and getattr(token, "access", None)
        and (getattr(token, "refresh", None) or (expires_at and expires_at > now_ms))
    )
    return OAuthProviderStatus(
        configured=configured,
        account=getattr(token, "account_id", None) if token else None,
        expires_at=expires_at,
        login_supported=True,
    )


def _github_copilot_status() -> OAuthProviderStatus:
    try:
        from nanobot.providers.github_copilot_provider import get_github_copilot_login_status
    except Exception:
        return OAuthProviderStatus(False, None, None, False)

    token = None
    with suppress(Exception):
        token = get_github_copilot_login_status()
    expires_at = _coerce_expires_ms(getattr(token, "expires", None)) if token else None
    configured = bool(
        token
        and getattr(token, "access", None)
        and expires_at
        and expires_at > int(time.time() * 1000)
    )
    return OAuthProviderStatus(
        configured=configured,
        account=getattr(token, "account_id", None) if token else None,
        expires_at=expires_at,
        login_supported=True,
    )


def _coerce_expires_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None
