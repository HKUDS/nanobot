"""Cron store service (pure local, no Pulsing required).

This module owns:
- Persistent storage (jobs.json)
- Next-run calculations
- CRUD operations for cron jobs

Execution (calling AgentActor, delivering to channel actors) is intentionally
NOT handled here; that's SchedulerActor's job.
"""

import time
import uuid
from pathlib import Path

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


def now_ms() -> int:
    return int(time.time() * 1000)


def compute_next_run(schedule: CronSchedule, base_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > base_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return base_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter

            cron = croniter(schedule.expr, time.time())
            next_time = cron.get_next()
            return int(next_time * 1000)
        except Exception:
            return None

    return None


class CronStoreService:
    """File-backed cron job store with scheduling helpers."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._store: CronStore | None = None

    # ── Persistence ──────────────────────────────────────────

    def load(self) -> CronStore:
        if self._store is not None:
            return self._store

        if self.store_path.exists():
            try:
                self._store = CronStore.model_validate_json(self.store_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
                self._store = CronStore()
        else:
            self._store = CronStore()

        return self._store

    def save(self) -> None:
        store = self.load()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(store.model_dump_json(by_alias=True, indent=2))

    # ── Scheduling helpers ───────────────────────────────────

    def recompute_next_runs(self) -> None:
        store = self.load()
        base = now_ms()
        for job in store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = compute_next_run(job.schedule, base)

    def next_wake_at_ms(self) -> int | None:
        store = self.load()
        times = [
            j.state.next_run_at_ms
            for j in store.jobs
            if j.enabled and j.state.next_run_at_ms
        ]
        return min(times) if times else None

    def due_jobs(self, at_ms: int | None = None) -> list[CronJob]:
        store = self.load()
        at_ms = at_ms or now_ms()
        return [
            j
            for j in store.jobs
            if j.enabled and j.state.next_run_at_ms and at_ms >= j.state.next_run_at_ms
        ]

    def mark_job_finished(
        self,
        job: CronJob,
        ok: bool,
        error: str | None = None,
        started_at_ms: int | None = None,
    ) -> None:
        """Update job state after an execution attempt (success or failure)."""
        job.state.last_status = "ok" if ok else "error"
        job.state.last_error = None if ok else (error or "unknown error")
        job.state.last_run_at_ms = started_at_ms or now_ms()
        job.updated_at_ms = now_ms()

        if job.schedule.kind == "at":
            if job.delete_after_run:
                store = self.load()
                store.jobs = [j for j in store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            job.state.next_run_at_ms = compute_next_run(job.schedule, now_ms())

    # ── CRUD ────────────────────────────────────────────────

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        store = self.load()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float("inf"))

    def get_job(self, job_id: str) -> CronJob | None:
        store = self.load()
        return next((j for j in store.jobs if j.id == job_id), None)

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob:
        store = self.load()
        base = now_ms()

        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=compute_next_run(schedule, base)),
            created_at_ms=base,
            updated_at_ms=base,
            delete_after_run=delete_after_run,
        )

        store.jobs.append(job)
        self.save()
        return job

    def remove_job(self, job_id: str) -> bool:
        store = self.load()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before
        if removed:
            self.save()
        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        job = self.get_job(job_id)
        if not job:
            return None

        job.enabled = enabled
        job.updated_at_ms = now_ms()
        if enabled:
            job.state.next_run_at_ms = compute_next_run(job.schedule, now_ms())
        else:
            job.state.next_run_at_ms = None

        self.save()
        return job

