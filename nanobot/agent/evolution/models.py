"""Data models for turn execution traces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

TurnTraceOutcome = Literal["success", "fail", "partial"]


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Minimal tool invocation record stored on a turn trace."""

    name: str
    args_summary: str = ""
    ok: bool = True
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "args_summary": self.args_summary,
            "ok": self.ok,
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCallRecord:
        duration = data.get("duration_ms")
        return cls(
            name=str(data.get("name") or ""),
            args_summary=str(data.get("args_summary") or ""),
            ok=bool(data.get("ok", True)),
            duration_ms=int(duration) if duration is not None else None,
        )


@dataclass(frozen=True, slots=True)
class TurnTrace:
    """One user turn's execution trace for PostTask and GEPA."""

    session_key: str
    query: str
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    turn_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    skills_injected: tuple[str, ...] = ()
    tool_calls: tuple[ToolCallRecord, ...] = ()
    tool_call_count: int = 0
    iterations: int = 0
    stop_reason: str = ""
    outcome: TurnTraceOutcome = "success"
    token_usage: tuple[tuple[str, int], ...] = ()
    used_for_evolution: bool = False

    def __post_init__(self) -> None:
        if self.tool_call_count <= 0 and self.tool_calls:
            object.__setattr__(self, "tool_call_count", len(self.tool_calls))

    @property
    def token_usage_dict(self) -> dict[str, int]:
        return dict(self.token_usage)

    def to_row_values(self) -> tuple[Any, ...]:
        created_at = _parse_iso_timestamp(self.timestamp)
        return (
            self.trace_id,
            self.session_key,
            self.turn_id,
            self.timestamp,
            self.query,
            json.dumps(list(self.skills_injected), ensure_ascii=False),
            json.dumps([call.to_dict() for call in self.tool_calls], ensure_ascii=False),
            self.tool_call_count,
            self.iterations,
            self.stop_reason,
            self.outcome,
            json.dumps(self.token_usage_dict, ensure_ascii=False),
            int(self.used_for_evolution),
            created_at,
        )

    @classmethod
    def from_row(cls, row: Any) -> TurnTrace:
        skills = json.loads(row["skills_injected_json"] or "[]")
        tool_calls_raw = json.loads(row["tool_calls_json"] or "[]")
        token_usage_raw = json.loads(row["token_usage_json"] or "{}")
        return cls(
            trace_id=str(row["trace_id"]),
            session_key=str(row["session_key"]),
            turn_id=str(row["turn_id"]),
            timestamp=str(row["timestamp"]),
            query=str(row["query"]),
            skills_injected=tuple(str(name) for name in skills),
            tool_calls=tuple(ToolCallRecord.from_dict(item) for item in tool_calls_raw),
            tool_call_count=int(row["tool_call_count"]),
            iterations=int(row["iterations"]),
            stop_reason=str(row["stop_reason"]),
            outcome=row["outcome"],
            token_usage=tuple(token_usage_raw.items()),
            used_for_evolution=bool(row["used_for_evolution"]),
        )


def _parse_iso_timestamp(value: str) -> float:
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return datetime.now(UTC).timestamp()
