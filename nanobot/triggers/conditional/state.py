"""Durable per-monitor state for ConditionalTriggerRuntime.

- Survives gateway restarts (atomic JSON on disk).
- Holds last_check / last_trigger / dedupe / cooldown / backoff counters.
- One file per workspace: <workspace>/triggers/conditional/state.json

Design: single file with dict[monitor_id -> Record].  FileLock mirrors
CronService / LocalTriggerStore conventions (same lock style).
Ownership: only the gateway process writes; external collectors never touch it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock
from loguru import logger


@dataclass(slots=True)
class MonitorStateRecord:
    monitor_id: str
    last_check_at_ms: int | None = None
    last_trigger_at_ms: int | None = None
    last_dedupe_key: str | None = None
    cooldown_until_ms: int | None = None
    consecutive_failures: int = 0
    next_due_at_ms: int | None = None
    last_error: str | None = None
    updated_at_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitorStateRecord":
        return cls(
            monitor_id=str(data.get("monitor_id") or data.get("id") or ""),
            last_check_at_ms=data.get("last_check_at_ms"),
            last_trigger_at_ms=data.get("last_trigger_at_ms"),
            last_dedupe_key=data.get("last_dedupe_key"),
            cooldown_until_ms=data.get("cooldown_until_ms"),
            consecutive_failures=int(data.get("consecutive_failures") or 0),
            next_due_at_ms=data.get("next_due_at_ms"),
            last_error=data.get("last_error"),
            updated_at_ms=int(data.get("updated_at_ms") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "last_check_at_ms": self.last_check_at_ms,
            "last_trigger_at_ms": self.last_trigger_at_ms,
            "last_dedupe_key": self.last_dedupe_key,
            "cooldown_until_ms": self.cooldown_until_ms,
            "consecutive_failures": self.consecutive_failures,
            "next_due_at_ms": self.next_due_at_ms,
            "last_error": self.last_error,
            "updated_at_ms": self.updated_at_ms,
        }


class ConditionalStateStore:
    """Atomic JSON store for monitor states — mirrors CronService._atomic_write."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.root = self.workspace_path / "triggers" / "conditional"
        self.path = self.root / "state.json"
        self._lock = FileLock(str(self.root / ".lock"))

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, MonitorStateRecord]:
        self.ensure()
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("ConditionalState: failed to parse {}", self.path)
            return {}
        out: dict[str, MonitorStateRecord] = {}
        # Support both {"records": [...]} and {"monitors": {...}} shapes
        items: list[dict[str, Any]] = []
        if isinstance(raw, dict) and isinstance(raw.get("records"), list):
            items = [x for x in raw["records"] if isinstance(x, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("monitors"), dict):
            items = [v for v in raw["monitors"].values() if isinstance(v, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("version"), int):
            # tolerate legacy single-record file
            pass
        for d in items:
            try:
                rec = MonitorStateRecord.from_dict(d)
                if rec.monitor_id:
                    out[rec.monitor_id] = rec
            except Exception:
                continue
        return out

    def get(self, monitor_id: str) -> MonitorStateRecord | None:
        return self.load_all().get(monitor_id)

    def upsert(self, record: MonitorStateRecord) -> None:
        self.ensure()
        with self._lock:
            all_records = self.load_all()
            record.updated_at_ms = int(time.time() * 1000)
            all_records[record.monitor_id] = record
            self._save_unlocked(all_records)

    def touch_check(
        self,
        monitor_id: str,
        *,
        now_ms: int,
        next_due_at_ms: int | None = None,
        error: str | None = None,
        increment_failure: bool = False,
        reset_failures: bool = False,
    ) -> MonitorStateRecord:
        """Update last_check / failure counters atomically."""
        self.ensure()
        with self._lock:
            all_records = self.load_all()
            rec = all_records.get(monitor_id) or MonitorStateRecord(monitor_id=monitor_id)
            rec.last_check_at_ms = now_ms
            if next_due_at_ms is not None:
                rec.next_due_at_ms = next_due_at_ms
            if error is not None:
                rec.last_error = error[:2000]
            elif reset_failures:
                rec.last_error = None
            if increment_failure:
                rec.consecutive_failures += 1
            elif reset_failures:
                rec.consecutive_failures = 0
            rec.updated_at_ms = int(time.time() * 1000)
            all_records[monitor_id] = rec
            self._save_unlocked(all_records)
            return rec

    def record_trigger(
        self,
        monitor_id: str,
        *,
        now_ms: int,
        dedupe_key: str | None,
        cooldown_until_ms: int | None,
        next_due_at_ms: int | None = None,
    ) -> MonitorStateRecord:
        self.ensure()
        with self._lock:
            all_records = self.load_all()
            rec = all_records.get(monitor_id) or MonitorStateRecord(monitor_id=monitor_id)
            rec.last_check_at_ms = now_ms
            rec.last_trigger_at_ms = now_ms
            if dedupe_key is not None:
                rec.last_dedupe_key = dedupe_key
            if cooldown_until_ms is not None:
                rec.cooldown_until_ms = cooldown_until_ms
            rec.consecutive_failures = 0
            rec.last_error = None
            if next_due_at_ms is not None:
                rec.next_due_at_ms = next_due_at_ms
            rec.updated_at_ms = int(time.time() * 1000)
            all_records[monitor_id] = rec
            self._save_unlocked(all_records)
            return rec

    def _save_unlocked(self, records: dict[str, MonitorStateRecord]) -> None:
        payload = {
            "version": 1,
            "updated_at_ms": int(time.time() * 1000),
            "records": [r.to_dict() for r in sorted(records.values(), key=lambda x: x.monitor_id)],
        }
        self._atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        import errno, uuid

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            try:
                fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    try:
                        os.fsync(fd)
                    except OSError as e:
                        if e.errno != errno.EINVAL:
                            raise
                finally:
                    os.close(fd)
            except PermissionError:
                pass
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
