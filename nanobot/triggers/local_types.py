"""Persistent types for local triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from nanobot.utils.dict_keys import get_camel_snake as _get

TriggerStatus = Literal["ok", "error"]


@dataclass
class TriggerRunRecord:
    """A single local trigger delivery record."""

    run_at_ms: int
    status: TriggerStatus
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TriggerRunRecord":
        return cls(
            run_at_ms=int(_get(data, "runAtMs", "run_at_ms", 0)),
            status=str(data.get("status") or "error"),  # type: ignore[arg-type]
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runAtMs": self.run_at_ms,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class LocalTrigger:
    """A session-bound local trigger."""

    id: str
    name: str
    enabled: bool
    channel: str
    chat_id: str
    session_key: str
    sender_id: str = "trigger"
    origin_metadata: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    last_run_at_ms: int | None = None
    last_status: TriggerStatus | None = None
    last_error: str | None = None
    run_history: list[TriggerRunRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocalTrigger":
        history = [
            record if isinstance(record, TriggerRunRecord) else TriggerRunRecord.from_dict(record)
            for record in data.get("runHistory", data.get("run_history", []))
            if isinstance(record, (dict, TriggerRunRecord))
        ]
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            enabled=bool(data.get("enabled", True)),
            channel=str(data.get("channel") or ""),
            chat_id=str(_get(data, "chatId", "chat_id", "")),
            session_key=str(_get(data, "sessionKey", "session_key", "")),
            sender_id=str(_get(data, "senderId", "sender_id", "trigger") or "trigger"),
            origin_metadata=dict(_get(data, "originMetadata", "origin_metadata", {}) or {}),
            created_at_ms=int(_get(data, "createdAtMs", "created_at_ms", 0)),
            updated_at_ms=int(_get(data, "updatedAtMs", "updated_at_ms", 0)),
            last_run_at_ms=_get(data, "lastRunAtMs", "last_run_at_ms"),
            last_status=_get(data, "lastStatus", "last_status"),  # type: ignore[arg-type]
            last_error=_get(data, "lastError", "last_error"),
            run_history=history,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "channel": self.channel,
            "chatId": self.chat_id,
            "sessionKey": self.session_key,
            "senderId": self.sender_id,
            "originMetadata": self.origin_metadata,
            "createdAtMs": self.created_at_ms,
            "updatedAtMs": self.updated_at_ms,
            "lastRunAtMs": self.last_run_at_ms,
            "lastStatus": self.last_status,
            "lastError": self.last_error,
            "runHistory": [record.to_dict() for record in self.run_history],
        }


@dataclass
class TriggerDelivery:
    """One pending local trigger delivery written by the CLI."""

    id: str
    trigger_id: str
    content: str
    created_at_ms: int
    attempts: int = 0
    last_error: str | None = None
    path: Path | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        path: Path | None = None,
    ) -> "TriggerDelivery":
        return cls(
            id=str(data["id"]),
            trigger_id=str(_get(data, "triggerId", "trigger_id", "")),
            content=str(data.get("content") or ""),
            created_at_ms=int(_get(data, "createdAtMs", "created_at_ms", 0)),
            attempts=int(data.get("attempts", 0)),
            last_error=data.get("lastError") or data.get("last_error"),
            path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "triggerId": self.trigger_id,
            "content": self.content,
            "createdAtMs": self.created_at_ms,
            "attempts": self.attempts,
            "lastError": self.last_error,
        }
