"""Resume interrupted isolated work from the external ten-minute supervisor."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

from nanobot.development.config import DevelopmentConfig
from nanobot.development.service import DevelopmentService
from nanobot.operations.state import read_state, write_state


class RecoveryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checked_at: float = 0
    action: Literal["idle", "paused", "held", "resume", "unavailable"] = "idle"
    reason: str = ""
    job_id: str | None = None
    attempts: list[float] = Field(default_factory=list)


def recover(config: DevelopmentConfig, workspace: Path, config_path: Path) -> RecoveryRecord:
    if not config.enable or not config.resume_on_restart:
        return RecoveryRecord(reason="development_recovery_disabled")
    service = DevelopmentService(config, workspace, config_path)
    path = service.store.root / "recovery.json"
    with FileLock(str(path) + ".lock", timeout=0):
        stored = read_state(path)
        record = RecoveryRecord.model_validate(stored) if stored else RecoveryRecord()
        now = time.time()
        record.checked_at = now
        record.attempts = [value for value in record.attempts if value > now - 3600]
        service.reconcile()
        project = service.store.read()
        job = next((item for item in project.jobs if item.stage == "held"), None)
        if project.paused:
            record.action, record.reason = "paused", "operator_paused"
        elif job is None:
            record.action, record.reason = "idle", "no_interrupted_job"
        elif job.hold_kind not in {"interrupted", "paused", "budget"}:
            record.action, record.reason = "held", "manual_inspection_required"
        elif (job.hold_kind == "budget"
              and datetime.fromtimestamp(job.updated_at, timezone.utc).date()
              >= datetime.fromtimestamp(now, timezone.utc).date()):
            record.action, record.reason = "held", "daily_budget_waiting_for_reset"
        elif config.worker_backend != "systemd":
            record.action, record.reason = "held", "independent_worker_service_required"
        elif len(record.attempts) >= 3:
            record.action, record.reason = "held", "resume_budget_exhausted"
        else:
            record.action, record.reason, record.job_id = "resume", "checkpoint_continuation", job.id
            record.attempts.append(now)
            # Record dispatch BEFORE the external action. A crash cannot erase
            # the retry budget; the worker lease prevents simultaneous builders.
            write_state(path, record.model_dump(mode="json"))
            try:
                service.start(job.id)
            except (ValueError, OSError, TimeoutError):
                record.action, record.reason = "unavailable", "worker_service_launch_failed"
        write_state(path, record.model_dump(mode="json"))
        return record
