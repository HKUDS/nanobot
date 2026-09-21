"""Stable request and error contracts shared by WebUI settings domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

QueryParams = dict[str, list[str]]


@dataclass(frozen=True)
class SettingsRequest:
    """Transport-neutral input decoded by the settings route facade."""

    query: QueryParams
    payload: dict[str, Any] | None = None
    local_browser: bool = False


@dataclass(frozen=True)
class SettingsRouteResult:
    """Transport-neutral result returned by a settings domain handler."""

    payload: dict[str, Any] | None = None
    status: int = 200
    error: str | None = None
    decorate_restart: bool = False
    restart_section: str | None = None
    clear_restart_section: str | None = None
    restart_payload_key: str | None = None

    @classmethod
    def success(
        cls,
        payload: dict[str, Any],
        *,
        decorate_restart: bool = False,
        restart_section: str | None = None,
        clear_restart_section: str | None = None,
        restart_payload_key: str | None = None,
    ) -> SettingsRouteResult:
        return cls(
            payload=payload,
            decorate_restart=decorate_restart,
            restart_section=restart_section,
            clear_restart_section=clear_restart_section,
            restart_payload_key=restart_payload_key,
        )

    @classmethod
    def failure(cls, status: int, error: str) -> SettingsRouteResult:
        return cls(status=status, error=error)


class WebUISettingsError(ValueError):
    """User-facing settings validation failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def query_first_alias(query: QueryParams, snake: str, camel: str) -> str | None:
    value = query_first(query, snake)
    return query_first(query, camel) if value is None else value


def query_has_alias(query: QueryParams, snake: str, camel: str) -> bool:
    return snake in query or camel in query


def parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"1", "0", "true", "false", "yes", "no"}:
        raise WebUISettingsError(f"{field} must be boolean")
    return normalized in {"1", "true", "yes"}
