"""Durable mailbox primitives for manager-worker task coordination."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir, safe_filename

TaskState = str  # running | completed | failed | cancelled
MailboxReadState = str  # ready | running | not_found | consumed | timeout


@dataclass(slots=True)
class TaskRequest:
    """Task request recorded when the manager dispatches a worker."""

    task_id: str
    session_key: str
    label: str
    task: str
    origin: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class TaskResult:
    """Worker result written to the manager mailbox."""

    task_id: str
    session_key: str
    label: str
    task: str
    status: str
    content: str
    sender: str = "subagent"
    completed_at: float = field(default_factory=time.time)
    dedupe_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskSnapshot:
    """Read-only view of a task in the mailbox."""

    task_id: str
    session_key: str
    label: str
    task: str
    state: TaskState
    created_at: float
    completed_at: float | None = None
    consumed_at: float | None = None
    result_status: str | None = None
    error: str | None = None


@dataclass(slots=True)
class MailboxRead:
    """Result of a mailbox wait/consume operation."""

    state: MailboxReadState
    task: TaskSnapshot | None = None
    result: TaskResult | None = None


@dataclass(slots=True)
class _TaskRecord:
    request: TaskRequest
    state: TaskState = "running"
    result: TaskResult | None = None
    consumed_at: float | None = None
    completed_at: float | None = None
    error: str | None = None


class MailboxStore:
    """Durable task mailbox for local subagent coordination.

    JSON files are the source of truth. The condition variable only wakes
    waiters inside this process; persisted records remain readable after a
    manager restart.
    """

    def __init__(self, workspace: str | Path, *, root: str | Path | None = None) -> None:
        base = Path(root).expanduser() if root is not None else Path(workspace) / "tasks" / "subagents"
        self.root = ensure_dir(base)
        self._changed = asyncio.Condition()

    async def dispatch(self, request: TaskRequest) -> None:
        """Record that a task was dispatched."""
        async with self._changed:
            path, record = self._load_by_task_id(request.task_id, session_key=request.session_key)
            if record is not None:
                return
            path = self._record_path(request.session_key, request.task_id)
            self._write_record(path, _TaskRecord(request=request))
            self._changed.notify_all()

    async def record_result(self, result: TaskResult) -> bool:
        """Record a worker result.

        Returns ``True`` when this call writes a new terminal result and
        ``False`` when the task was already finalized.
        """
        async with self._changed:
            path, record = self._load_by_task_id(result.task_id, session_key=result.session_key)
            if record is None:
                request = TaskRequest(
                    task_id=result.task_id,
                    session_key=result.session_key,
                    label=result.label,
                    task=result.task,
                    origin=dict(result.metadata),
                    created_at=result.completed_at,
                )
                record = _TaskRecord(request=request)
                path = self._record_path(result.session_key, result.task_id)
            elif record.result is not None or record.state != "running":
                return False

            record.result = result
            record.completed_at = result.completed_at
            record.state = self._state_for_result(result.status)
            record.error = result.content if result.status in {"error", "cancelled"} else None
            self._write_record(path, record)
            self._changed.notify_all()
            return True

    async def mark_cancelled(
        self,
        task_id: str,
        *,
        session_key: str | None = None,
        reason: str = "Cancelled.",
    ) -> bool:
        """Mark a task cancelled and make the cancellation consumable once."""
        async with self._changed:
            path, record = self._load_by_task_id(task_id, session_key=session_key)
            if record is None or record.result is not None or record.state != "running":
                return False
            result = TaskResult(
                task_id=task_id,
                session_key=record.request.session_key,
                label=record.request.label,
                task=record.request.task,
                status="cancelled",
                content=reason,
                dedupe_key=task_id,
            )
            record.result = result
            record.completed_at = result.completed_at
            record.state = "cancelled"
            record.error = reason
            self._write_record(path, record)
            self._changed.notify_all()
            return True

    async def poll(
        self,
        session_key: str,
        *,
        task_id: str | None = None,
    ) -> list[TaskSnapshot]:
        """Return snapshots for one task or all tasks in a session."""
        async with self._changed:
            return self.snapshot_sync(session_key, task_id=task_id)

    def snapshot_sync(
        self,
        session_key: str,
        *,
        task_id: str | None = None,
    ) -> list[TaskSnapshot]:
        """Synchronous snapshot used while building runtime context."""
        if task_id is not None:
            _, record = self._load_by_task_id(task_id, session_key=session_key)
            if record is None:
                return []
            return [self._snapshot(record)]

        records = self._load_session_records(session_key)
        snapshots = [self._snapshot(record) for record in records]
        snapshots.sort(key=lambda item: (item.completed_at is None, item.created_at, item.task_id))
        return snapshots

    async def wait_for_result(
        self,
        session_key: str,
        *,
        task_id: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> MailboxRead:
        """Wait for and consume a result once."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        async with self._changed:
            while True:
                read = self._consume_ready_locked(session_key, task_id)
                if read.state != "running":
                    return read
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return MailboxRead("timeout", task=read.task)
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return MailboxRead("timeout", task=read.task)

    def _consume_ready_locked(
        self,
        session_key: str,
        task_id: str | None,
    ) -> MailboxRead:
        if task_id is not None:
            path, record = self._load_by_task_id(task_id, session_key=session_key)
            if record is None:
                return MailboxRead("not_found")
            snapshot = self._snapshot(record)
            if record.result is None:
                return MailboxRead("running", task=snapshot)
            if record.consumed_at is not None:
                return MailboxRead("consumed", task=snapshot, result=record.result)
            record.consumed_at = time.time()
            self._write_record(path, record)
            return MailboxRead("ready", task=self._snapshot(record), result=record.result)

        records_with_paths = self._load_session_records_with_paths(session_key)
        ready = [
            (path, record)
            for path, record in records_with_paths
            if record.result is not None and record.consumed_at is None
        ]
        if ready:
            ready.sort(key=lambda item: (
                item[1].completed_at or item[1].request.created_at,
                item[1].request.task_id,
            ))
            path, record = ready[0]
            record.consumed_at = time.time()
            self._write_record(path, record)
            return MailboxRead("ready", task=self._snapshot(record), result=record.result)

        running = [record for _, record in records_with_paths if record.result is None]
        if running:
            running.sort(key=lambda record: (record.request.created_at, record.request.task_id))
            return MailboxRead("running", task=self._snapshot(running[0]))
        if records_with_paths:
            records = [record for _, record in records_with_paths]
            records.sort(key=lambda record: (
                record.completed_at or record.request.created_at,
                record.request.task_id,
            ))
            return MailboxRead("consumed", task=self._snapshot(records[-1]))
        return MailboxRead("not_found")

    def _session_dir(self, session_key: str) -> Path:
        return self.root / safe_filename(session_key)

    def _record_path(self, session_key: str, task_id: str) -> Path:
        return ensure_dir(self._session_dir(session_key)) / f"{safe_filename(task_id)}.json"

    def _load_by_task_id(
        self,
        task_id: str,
        *,
        session_key: str | None = None,
    ) -> tuple[Path, _TaskRecord | None]:
        if session_key is not None:
            path = self._record_path(session_key, task_id)
            return path, self._read_record(path)

        filename = f"{safe_filename(task_id)}.json"
        for path in self.root.glob(f"*/{filename}"):
            record = self._read_record(path)
            if record is not None:
                return path, record
        return self.root / "_missing" / filename, None

    def _load_session_records(self, session_key: str) -> list[_TaskRecord]:
        return [record for _, record in self._load_session_records_with_paths(session_key)]

    def _load_session_records_with_paths(self, session_key: str) -> list[tuple[Path, _TaskRecord]]:
        directory = self._session_dir(session_key)
        if not directory.exists():
            return []
        records: list[tuple[Path, _TaskRecord]] = []
        for path in directory.glob("*.json"):
            record = self._read_record(path)
            if record is not None:
                records.append((path, record))
        return records

    def _read_record(self, path: Path) -> _TaskRecord | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._record_from_json(data)
        except Exception:
            return None

    def _write_record(self, path: Path, record: _TaskRecord) -> None:
        ensure_dir(path.parent)
        payload = json.dumps(self._record_to_json(record), ensure_ascii=False, indent=2)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.write("\n")
                with suppress(OSError):
                    os.fsync(f.fileno())
            os.replace(tmp, path)
            with suppress(OSError):
                fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _record_to_json(record: _TaskRecord) -> dict[str, Any]:
        result = record.result
        return {
            "version": 1,
            "task_id": record.request.task_id,
            "session_key": record.request.session_key,
            "label": record.request.label,
            "task": record.request.task,
            "origin": record.request.origin,
            "state": record.state,
            "result": None if result is None else {
                "task_id": result.task_id,
                "session_key": result.session_key,
                "label": result.label,
                "task": result.task,
                "status": result.status,
                "content": result.content,
                "sender": result.sender,
                "completed_at": result.completed_at,
                "dedupe_key": result.dedupe_key,
                "metadata": result.metadata,
            },
            "consumed_at": record.consumed_at,
            "created_at": record.request.created_at,
            "completed_at": record.completed_at,
            "updated_at": time.time(),
            "error": record.error,
        }

    @staticmethod
    def _record_from_json(data: dict[str, Any]) -> _TaskRecord:
        request = TaskRequest(
            task_id=str(data["task_id"]),
            session_key=str(data["session_key"]),
            label=str(data.get("label") or data["task_id"]),
            task=str(data.get("task") or ""),
            origin=dict(data.get("origin") or {}),
            created_at=float(data.get("created_at") or time.time()),
        )
        raw_result = data.get("result")
        result = None
        if isinstance(raw_result, dict):
            result = TaskResult(
                task_id=str(raw_result.get("task_id") or request.task_id),
                session_key=str(raw_result.get("session_key") or request.session_key),
                label=str(raw_result.get("label") or request.label),
                task=str(raw_result.get("task") or request.task),
                status=str(raw_result.get("status") or "error"),
                content=str(raw_result.get("content") or ""),
                sender=str(raw_result.get("sender") or "subagent"),
                completed_at=float(raw_result.get("completed_at") or time.time()),
                dedupe_key=raw_result.get("dedupe_key"),
                metadata=dict(raw_result.get("metadata") or {}),
            )
        return _TaskRecord(
            request=request,
            state=str(data.get("state") or "running"),
            result=result,
            consumed_at=data.get("consumed_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
        )

    @staticmethod
    def _state_for_result(status: str) -> TaskState:
        if status == "ok":
            return "completed"
        if status == "cancelled":
            return "cancelled"
        return "failed"

    @staticmethod
    def _snapshot(record: _TaskRecord) -> TaskSnapshot:
        result = record.result
        return TaskSnapshot(
            task_id=record.request.task_id,
            session_key=record.request.session_key,
            label=record.request.label,
            task=record.request.task,
            state=record.state,
            created_at=record.request.created_at,
            completed_at=record.completed_at,
            consumed_at=record.consumed_at,
            result_status=result.status if result is not None else None,
            error=record.error,
        )
