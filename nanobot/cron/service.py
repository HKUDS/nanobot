"""Cron service for scheduling agent tasks."""

import asyncio
import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal

from filelock import FileLock
from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronRunRecord, CronSchedule, CronStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter
            # Use caller-provided reference time for deterministic scheduling
            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None

    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """Validate schedule fields that would otherwise create non-runnable jobs."""
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")

    if schedule.kind == "cron" and schedule.tz:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(schedule.tz)
        except Exception:
            raise ValueError(f"unknown timezone '{schedule.tz}'") from None


class CronService:
    """Service for managing and executing scheduled jobs."""

    _MAX_RUN_HISTORY = 20

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
        max_sleep_ms: int = 300_000,  # 5 minutes
    ):
        self.store_path = store_path
        self._action_path = store_path.parent / "action.jsonl"
        self._lock = FileLock(str(self._action_path.parent) + ".lock")
        self.on_job = on_job
        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self.max_sleep_ms = max_sleep_ms

    def _load_jobs(self) -> tuple[list[CronJob], int]:
        jobs = []
        version = 1
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                jobs = []
                version = data.get("version", 1)
                for j in data.get("jobs", []):
                    jobs.append(CronJob(
                        id=j["id"],
                        name=j["name"],
                        enabled=j.get("enabled", True),
                        schedule=CronSchedule(
                            kind=j["schedule"]["kind"],
                            at_ms=j["schedule"].get("atMs"),
                            every_ms=j["schedule"].get("everyMs"),
                            expr=j["schedule"].get("expr"),
                            tz=j["schedule"].get("tz"),
                        ),
                        payload=CronPayload(
                            kind=j["payload"].get("kind", "agent_turn"),
                            message=j["payload"].get("message", ""),
                            deliver=j["payload"].get("deliver", False),
                            channel=j["payload"].get("channel"),
                            to=j["payload"].get("to"),
                        ),
                        state=CronJobState(
                            next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                            last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                            last_status=j.get("state", {}).get("lastStatus"),
                            last_error=j.get("state", {}).get("lastError"),
                            run_history=[
                                CronRunRecord(
                                    run_at_ms=r["runAtMs"],
                                    status=r["status"],
                                    duration_ms=r.get("durationMs", 0),
                                    error=r.get("error"),
                                )
                                for r in j.get("state", {}).get("runHistory", [])
                            ],
                        ),
                        created_at_ms=j.get("createdAtMs", 0),
                        updated_at_ms=j.get("updatedAtMs", 0),
                        delete_after_run=j.get("deleteAfterRun", False),
                    ))
            except Exception as e:
                logger.warning("Failed to load cron store: {}", e)
        return jobs, version

    def _merge_action(self):
        if not self._action_path.exists():
            return

        jobs_map = {j.id: j for j in self._store.jobs}
        def _update(params: dict):
            j = CronJob.from_dict(params)
            jobs_map[j.id] = j

        def _del(params: dict):
            if job_id := params.get("job_id"):
                jobs_map.pop(job_id)

        with self._lock:
            with open(self._action_path, "r", encoding="utf-8") as f:
                changed = False
                for line in f:
                    try:
                        line = line.strip()
                        action = json.loads(line)
                        if "action" not in action:
                            continue
                        if action["action"] == "del":
                            _del(action.get("params", {}))
                        else:
                            _update(action.get("params", {}))
                        changed = True
                    except Exception as exp:
                        logger.debug(f"load action line error: {exp}")
                        continue
            self._store.jobs = list(jobs_map.values())
            if self._running and changed:
                self._action_path.write_text("", encoding="utf-8")
                self._save_store()
        return

    def _load_store(self) -> CronStore:
        """Load jobs from disk. Reloads automatically if file was modified externally.
        - Reload every time because it needs to merge operations on the jobs object from other instances.
        """
        jobs, version = self._load_jobs()
        self._store = CronStore(version=version, jobs=jobs)
        self._merge_action()

        return self._store

    def _save_store(self) -> None:
        """Save jobs to disk."""
        if not self._store:
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                        "runHistory": [
                            {
                                "runAtMs": r.run_at_ms,
                                "status": r.status,
                                "durationMs": r.duration_ms,
                                "error": r.error,
                            }
                            for r in j.state.run_history
                        ],
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }

        self.store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()
        logger.info("Cron service started with {} jobs", len(self._store.jobs if self._store else []))

    def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)

    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all jobs."""
        if not self._store:
            return None
        times = [j.state.next_run_at_ms for j in self._store.jobs
                 if j.enabled and j.state.next_run_at_ms]
        return min(times) if times else None

    def _arm_timer(self) -> None:
        """Schedule the next timer tick."""
        if self._timer_task:
            self._timer_task.cancel()

        if not self._running:
            return

        next_wake = self._get_next_wake_ms()
        if next_wake is None:
            delay_ms = self.max_sleep_ms
        else:
            delay_ms = min(self.max_sleep_ms, max(0, next_wake - _now_ms()))
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """Handle timer tick - run due jobs."""
        self._load_store()
        if not self._store:
            return

        now = _now_ms()
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        for job in due_jobs:
            await self._execute_job(job)

        self._save_store()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)

        try:
            if self.on_job:
                await self.on_job(job)

            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error("Cron: job '{}' failed: {}", job.name, e)

        end_ms = _now_ms()
        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = end_ms

        job.state.run_history.append(CronRunRecord(
            run_at_ms=start_ms,
            status=job.state.last_status,
            duration_ms=end_ms - start_ms,
            error=job.state.last_error,
        ))
        job.state.run_history = job.state.run_history[-self._MAX_RUN_HISTORY:]

        # Handle one-shot jobs
        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # Compute next run
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    def _append_action(self, action: Literal["add", "del", "update"], params: dict):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(self._action_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"action": action, "params": params}, ensure_ascii=False) + "\n")


    # ========== Public API ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))

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
        """Add a new job."""
        _validate_schedule_for_add(schedule)
        now = _now_ms()

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
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )
        if self._running:
            store = self._load_store()
            store.jobs.append(job)
            self._save_store()
            self._arm_timer()
        else:
            self._append_action("add", asdict(job))

        logger.info("Cron: added job '{}' ({})", name, job.id)
        return job

    def register_system_job(self, job: CronJob) -> CronJob:
        """Register an internal system job (idempotent on restart)."""
        store = self._load_store()
        now = _now_ms()
        job.state = CronJobState(next_run_at_ms=_compute_next_run(job.schedule, now))
        job.created_at_ms = now
        job.updated_at_ms = now
        store.jobs = [j for j in store.jobs if j.id != job.id]
        store.jobs.append(job)
        self._save_store()
        self._arm_timer()
        logger.info("Cron: registered system job '{}' ({})", job.name, job.id)
        return job

    def remove_job(self, job_id: str) -> Literal["removed", "protected", "not_found"]:
        """Remove a job by ID, unless it is a protected system job."""
        store = self._load_store()
        job = next((j for j in store.jobs if j.id == job_id), None)
        if job is None:
            return "not_found"
        if job.payload.kind == "system_event":
            logger.info("Cron: refused to remove protected system job {}", job_id)
            return "protected"

        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            if self._running:
                self._save_store()
                self._arm_timer()
            else:
                self._append_action("del", {"job_id": job_id})
            logger.info("Cron: removed job {}", job_id)
            return "removed"

        return "not_found"

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    job.state.next_run_at_ms = None
                if self._running:
                    self._save_store()
                    self._arm_timer()
                else:
                    self._append_action("update", asdict(job))
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job without disturbing the service's running state."""
        was_running = self._running
        self._running = True
        try:
            store = self._load_store()
            for job in store.jobs:
                if job.id == job_id:
                    if not force and not job.enabled:
                        return False
                    await self._execute_job(job)
                    self._save_store()
                    return True
            return False
        finally:
            self._running = was_running
            if was_running:
                self._arm_timer()

    def get_job(self, job_id: str) -> CronJob | None:
        """Get a job by ID."""
        store = self._load_store()
        return next((j for j in store.jobs if j.id == job_id), None)

    def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
