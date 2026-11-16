"""Private outbox for canonical messages appended outside the active turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4


@dataclass
class HistoryReplayBatch:
    messages: list[dict[str, Any]]
    id: str = field(default_factory=lambda: uuid4().hex)

    def to_record(self) -> dict[str, Any]:
        return {"id": self.id, "messages": self.messages}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> HistoryReplayBatch:
        identifier = cast(object, record.get("id"))
        messages = cast(object, record.get("messages"))
        if not isinstance(identifier, str) or not identifier or not isinstance(messages, list):
            raise ValueError("invalid history replay batch")
        records: list[dict[str, Any]] = []
        for message in cast(list[object], messages):
            if not isinstance(message, dict):
                raise ValueError("invalid history replay message")
            item = cast(dict[str, Any], message)
            if item.get("role") not in {"user", "assistant", "tool", "system"} or "content" not in item:
                raise ValueError("invalid history replay message")
            records.append(item)
        return cls(records, id=identifier)
