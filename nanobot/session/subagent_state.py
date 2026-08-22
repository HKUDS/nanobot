"""Durable lifecycle records for subagent tasks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from nanobot.session.manager import SessionManager

SUBAGENT_TASKS_METADATA_KEY = "subagent_tasks.v1"
SUBAGENT_DETAILS_METADATA_KEY = "subagent_details.v1"
SUBAGENT_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
SUBAGENT_ACTIVE_STATUSES = frozenset({"queued", "running"})
MAX_PERSISTED_SUBAGENT_TASKS = 100
MAX_PERSISTED_SUBAGENT_DETAILS = 50
MAX_DETAIL_STEPS = 100
MAX_DETAIL_TEXT = 12000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SubagentTaskRecord:
    task_id: str
    label: str
    task_description: str
    status: str
    channel: str
    chat_id: str
    session_key: str
    turn_id: str | None
    created_at: str
    updated_at: str
    revision: int = 0
    stop_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "label": self.label,
            "task_description": self.task_description,
            "status": self.status,
            "channel": self.channel,
            "chat_id": self.chat_id,
            "session_key": self.session_key,
            "turn_id": self.turn_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SubagentTaskRecord | None":
        if not isinstance(value, dict):
            return None
        required = ("task_id", "label", "task_description", "status", "channel", "chat_id", "session_key")
        if any(not isinstance(value.get(key), str) or not value[key] for key in required):
            return None
        status = value["status"]
        if status not in SUBAGENT_ACTIVE_STATUSES | SUBAGENT_TERMINAL_STATUSES:
            return None
        revision = value.get("revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            revision = 0
        turn_id = value.get("turn_id")
        return cls(
            task_id=value["task_id"],
            label=value["label"],
            task_description=value["task_description"],
            status=status,
            channel=value["channel"],
            chat_id=value["chat_id"],
            session_key=value["session_key"],
            turn_id=turn_id if isinstance(turn_id, str) and turn_id else None,
            created_at=value.get("created_at") if isinstance(value.get("created_at"), str) else _now(),
            updated_at=value.get("updated_at") if isinstance(value.get("updated_at"), str) else _now(),
            revision=revision,
            stop_reason=value.get("stop_reason") if isinstance(value.get("stop_reason"), str) else None,
            error=value.get("error") if isinstance(value.get("error"), str) else None,
        )


class SubagentTaskStore:
    """Persist task records in the existing session metadata JSONL."""

    def __init__(self, sessions: SessionManager | None) -> None:
        self.sessions = sessions

    def _load(self, session_key: str) -> list[SubagentTaskRecord]:
        if self.sessions is None:
            return []
        session = self.sessions.get_or_create(session_key)
        raw = session.metadata.get(SUBAGENT_TASKS_METADATA_KEY, [])
        if not isinstance(raw, list):
            return []
        return [record for value in raw if (record := SubagentTaskRecord.from_dict(value)) is not None]

    def _save(self, session_key: str, records: Iterable[SubagentTaskRecord]) -> None:
        if self.sessions is None:
            return
        session = self.sessions.get_or_create(session_key)
        session.metadata[SUBAGENT_TASKS_METADATA_KEY] = [record.to_dict() for record in records]
        self.sessions.save(session)

    def upsert(self, record: SubagentTaskRecord) -> SubagentTaskRecord:
        records = self._load(record.session_key)
        if not record.created_at or not record.updated_at:
            timestamp = _now()
            record = replace(
                record,
                created_at=record.created_at or timestamp,
                updated_at=record.updated_at or timestamp,
            )
        next_record = record
        for index, existing in enumerate(records):
            if existing.task_id == record.task_id:
                next_record = replace(record, revision=existing.revision + 1, updated_at=_now())
                records[index] = next_record
                break
        else:
            records.append(record)
        records.sort(key=lambda item: (item.updated_at, item.task_id), reverse=True)
        self._save(record.session_key, records[:MAX_PERSISTED_SUBAGENT_TASKS])
        return next_record

    def snapshot(self, session_key: str, active_task_ids: set[str] | None = None) -> list[SubagentTaskRecord]:
        records = self._load(session_key)
        changed = False
        if active_task_ids is not None:
            repaired: list[SubagentTaskRecord] = []
            for record in records:
                if record.status in SUBAGENT_ACTIVE_STATUSES and record.task_id not in active_task_ids:
                    record = replace(
                        record,
                        status="interrupted",
                        stop_reason="gateway_restart_or_runtime_loss",
                        updated_at=_now(),
                        revision=record.revision + 1,
                    )
                    changed = True
                repaired.append(record)
            records = repaired
            if changed:
                self._save(session_key, records)
        return records


@dataclass(frozen=True)
class SubagentDetailRecord:
    """Bounded replayable detail; live deltas remain process-local."""

    task_id: str
    label: str
    turn_id: str | None
    status: str
    revision: int
    seq: int
    input: str
    steps: list[dict[str, Any]]
    output: str
    stop_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "label": self.label,
            "turn_id": self.turn_id,
            "status": self.status,
            "revision": self.revision,
            "seq": self.seq,
            "input": self.input[-MAX_DETAIL_TEXT:],
            "steps": self.steps[-MAX_DETAIL_STEPS:],
            "output": self.output[-MAX_DETAIL_TEXT:],
            "stop_reason": self.stop_reason,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SubagentDetailRecord | None":
        if not isinstance(value, dict):
            return None
        task_id = value.get("task_id")
        label = value.get("label")
        if not isinstance(task_id, str) or not task_id or not isinstance(label, str):
            return None
        steps = value.get("steps")
        return cls(
            task_id=task_id,
            label=label,
            turn_id=value.get("turn_id") if isinstance(value.get("turn_id"), str) else None,
            status=value.get("status") if isinstance(value.get("status"), str) else "interrupted",
            revision=int(value.get("revision", 0)) if isinstance(value.get("revision", 0), int) else 0,
            seq=int(value.get("seq", 0)) if isinstance(value.get("seq", 0), int) else 0,
            input=value.get("input") if isinstance(value.get("input"), str) else "",
            steps=[item for item in steps if isinstance(item, dict)][-MAX_DETAIL_STEPS:]
            if isinstance(steps, list) else [],
            output=value.get("output") if isinstance(value.get("output"), str) else "",
            stop_reason=value.get("stop_reason") if isinstance(value.get("stop_reason"), str) else None,
            error=value.get("error") if isinstance(value.get("error"), str) else None,
        )


class SubagentDetailStore:
    """Persist only terminal/bounded detail snapshots in session metadata."""

    def __init__(self, sessions: SessionManager | None) -> None:
        self.sessions = sessions

    def _load(self, session_key: str) -> list[SubagentDetailRecord]:
        if self.sessions is None:
            return []
        session = self.sessions.get_or_create(session_key)
        raw = session.metadata.get(SUBAGENT_DETAILS_METADATA_KEY, [])
        if not isinstance(raw, list):
            return []
        return [record for value in raw if (record := SubagentDetailRecord.from_dict(value)) is not None]

    def upsert(self, session_key: str, record: SubagentDetailRecord) -> None:
        if self.sessions is None:
            return
        records = self._load(session_key)
        records = [item for item in records if item.task_id != record.task_id]
        records.insert(0, record)
        session = self.sessions.get_or_create(session_key)
        session.metadata[SUBAGENT_DETAILS_METADATA_KEY] = [
            item.to_dict() for item in records[:MAX_PERSISTED_SUBAGENT_DETAILS]
        ]
        self.sessions.save(session)

    def snapshot(self, session_key: str) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self._load(session_key)]
