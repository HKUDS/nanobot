from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

QueryParams = Mapping[str, list[str]]


class ChannelConnector(Protocol):
    """Channel-owned setup actions called by the settings request owner."""

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]: ...


@runtime_checkable
class ManagedChannelConnector(ChannelConnector, Protocol):
    """Setup whose detached work can participate in gateway maintenance.

    The synchronous property must stay true through awaited cleanup. ``close``
    returns only after owned writers have stopped; failure retains ownership.
    Settings requests account for their own awaited work separately.
    """

    @property
    def has_pending_work(self) -> bool: ...

    async def close(self) -> None: ...


class ChannelConnectError(Exception):
    """User-facing channel connection failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


__all__ = [
    "ChannelConnectError", "ChannelConnector", "ManagedChannelConnector", "QueryParams", "query_first",
]
