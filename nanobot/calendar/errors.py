"""Calendar domain errors and canonical error codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CalendarErrorCode:
    """Canonical calendar error codes."""

    AUTH_FAILED = "CAL_AUTH_FAILED"
    PERMISSION_DENIED = "CAL_PERMISSION_DENIED"
    NOT_FOUND = "CAL_NOT_FOUND"
    INVALID_ARGUMENT = "CAL_INVALID_ARGUMENT"
    PROVIDER_NOT_CONFIGURED = "CAL_PROVIDER_NOT_CONFIGURED"
    PROVIDER_UNAVAILABLE = "CAL_PROVIDER_UNAVAILABLE"
    UNKNOWN_PROVIDER = "CAL_UNKNOWN_PROVIDER"
    API_ERROR = "CAL_API_ERROR"


@dataclass
class CalendarError(Exception):
    """Calendar exception with stable machine-readable code."""

    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

