"""Small contract shared by channel-owned interactive connection flows."""

from __future__ import annotations

from collections.abc import Mapping

QueryParams = Mapping[str, list[str]]


class ChannelConnectError(Exception):
    """User-facing channel connection failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


__all__ = ["ChannelConnectError", "QueryParams", "query_first"]
