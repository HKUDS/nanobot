"""Result of an authenticated WebUI mutation, before WebSocket encoding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MutationResult:
    status_code: int
    result: dict[str, Any] | None = None
    message: str | None = None

    @classmethod
    def success(cls, result: dict[str, Any], *, status: int = 200) -> MutationResult:
        return cls(status_code=status, result=result)

    @classmethod
    def failure(cls, status: int, message: str | None) -> MutationResult:
        return cls(status_code=status, message=message)
