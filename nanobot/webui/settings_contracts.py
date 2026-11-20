from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

HttpQuery = dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class MutationParams:
    """Original JSON fields, distinct from multi-valued HTTP query strings."""

    values: dict[str, Any]

    def __contains__(self, key: str) -> bool:
        return key in self.values


QueryParams = HttpQuery | MutationParams


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


def parameter_value(query: QueryParams, key: str) -> Any:
    if isinstance(query, MutationParams):
        return query.values.get(key)
    values = query.get(key)
    return values[0] if values else None


def parameter_json(query: QueryParams, key: str, default: Any = None) -> Any:
    value = parameter_value(query, key)
    if value is None or value == "":
        return default
    return json.loads(value) if isinstance(value, str) else value


def query_first(query: QueryParams, key: str) -> str | None:
    value = parameter_value(query, key)
    if value is None:
        # An explicit null has historically meant a blank scalar.
        return "" if isinstance(query, MutationParams) and key in query else None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if isinstance(value, (str, int, float)) else None


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
