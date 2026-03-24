"""Cron service for scheduling agent tasks."""

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronRunRecord, CronSchedule, CronStore


def _now_ms() -> int:
    return int(time.time() * 1000)


_TOP_OF_HOUR_RE = re.compile(r"^0\s")


def _is_top_of_hour_expr(expr: str) -> bool:
    """Return True for recurring expressions that fire at the top of every hour."""
    parts = expr.strip().split()
    if len(parts) < 5:
        return False
    if parts[0] != "0":
        return False
    return parts[1] in ("*",) or parts[1].startswith("*/")


def _stagger_offset_ms(job_id: str, window_ms: int = 5 * 60 * 1000) -> int:
    """Deterministic per-job stagger offset from 0..window_ms."""
    h = int(hashlib.sha256(job_id.encode()).hexdigest()[:8], 16)
    return h % window_ms


def _compute_next_run(schedule: CronSchedule, now_ms: int, job_id: str = "") -> int | None:
    """Compute next run time in ms, applying stagger for top-of-hour recurring expressions."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            next_ms = int(next_dt.timestamp() * 1000)

            if schedule.stagger_ms is not None:
                stagger = schedule.stagger_ms
            elif _is_top_of_hour_expr(schedule.expr) and job_id:
                stagger = _stagger_offset_ms(job_id)
            else:
                stagger = 0

            return next_ms + stagger
        except Exception:
            return None

    return None


def _backoff_delay_ms(consecutive_errors: int) -> int:
    """Get backoff delay for the given error count (0-indexed)."""
    idx = min(consecutive_errors, len(DEFAULT_BACKOFF_MS) - 1)
    return DEFAULT_BACKOFF_MS[idx]


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


def _job_to_dict(j: CronJob) -> dict:
    """Serialize a CronJob to a JSON-safe dict."""
    return {
        "id": j.id,
        "name": j.name,
        "enabled": j.enabled,
        "schedule": {
            "kind": j.schedule.kind,
            "atMs": j.schedule.at_ms,
            "everyMs": j.schedule.every_ms,
            "expr": j.schedule.expr,
            "tz": j.schedule.tz,
            "staggerMs": j.schedule.stagger_ms,
        },
        "payload": {
            "kind": j.payload.kind,
            "message": j.payload.message,
            "deliver": j.payload.deliver,
            "channel": j.payload.channel,
            "to": j.payload.to,
        },
        "delivery": {
            "mode": j.delivery.mode,
            "channel": j.delivery.channel,
            "to": j.delivery.to,
            "bestEffort": j.delivery.best_effort,
        },
        "state": {
            "nextRunAtMs": j.state.next_run_at_ms,
            "lastRunAtMs": j.state.last_run_at_ms,
            "lastStatus": j.state.last_status,
            "lastError": j.state.last_error,
            "consecutiveErrors": j.state.consecutive_errors,
            "nextRetryAtMs": j.state.next_retry_at_ms,
        },
        "sessionTarget": j.session_target,
        "wakeMode": j.wake_mode,
        "createdAtMs": j.created_at_ms,
        "updatedAtMs": j.updated_at_ms,
        "deleteAfterRun": j.delete_after_run,
        "description": j.description,
    }


def _job_from_dict(j: dict) -> CronJob:
    """Deserialize a CronJob from a JSON dict."""
    sched = j.get("schedule", {})
    payload_data = j.get("payload", {})
    delivery_data = j.get("delivery", {})
    state_data = j.get("state", {})

    # Migrate legacy payload.deliver -> delivery config
    delivery_mode = delivery_data.get("mode", "none")
    delivery_channel = delivery_data.get("channel")
    delivery_to = delivery_data.get("to")
    if not delivery_data and payload_data.get("deliver"):
        delivery_mode = "announce"
        delivery_channel = payload_data.get("channel")
        delivery_to = payload_data.get("to")

    return CronJob(
        id=j["id"],
        name=j["name"],
        enabled=j.get("enabled", True),
        schedule=CronSchedule(
            kind=sched["kind"],
            at_ms=sched.get("atMs"),
            every_ms=sched.get("everyMs"),
            expr=sched.get("expr"),
            tz=sched.get("tz"),
            stagger_ms=sched.get("staggerMs"),
        ),
        payload=CronPayload(
            kind=payload_data.get("kind", "agent_turn"),
            message=payload_data.get("message", ""),
            deliver=payload_data.get("deliver", False),
            channel=payload_data.get("channel"),
            to=payload_data.get("to"),
        ),
        delivery=DeliveryConfig(
            mode=delivery_mode,
            channel=delivery_channel,
            to=delivery_to,
            best_effort=delivery_data.get("bestEffort", False),
        ),
        state=CronJobState(
            next_run_at_ms=state_data.get("nextRunAtMs"),
            last_run_at_ms=state_data.get("lastRunAtMs"),
            last_status=state_data.get("lastStatus"),
            last_error=state_data.get("lastError"),
            consecutive_errors=state_data.get("consecutiveErrors", 0),
            next_retry_at_ms=state_data.get("nextRetryAtMs"),
        ),
        session_target=j.get("sessionTarget", "isolated"),
        wake_mode=j.get("wakeMode", "now"),
        created_at_ms=j.get("createdAtMs", 0),
        updated_at_ms=j.get("updatedAtMs", 0),
        delete_after_run=j.get("deleteAfterRun", False),
        description=j.get("description", ""),
    )


class CronService:
    """Service for managing and executing scheduled jobs."""

    _MAX_RUN_HISTORY = 20

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
    ):
        self.store_path = store_path
        self.on_job = on_job
        self.max_concurrent_runs = max_concurrent_runs
        self._store: CronStore | None = None
        self._last_mtime: float = 0.0
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self._run_semaphore: asyncio.Semaphore | None = None
        self._runs_dir: Path = store_path.parent / "runs"

    # ========== Store I/O ==========

    def _load_store(self) -> CronStore:
        """Load jobs from disk. Reloads automatically if file was modified externally."""
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                logger.info("Cron: jobs.json modified externally, reloading")
                self._store = None
        if self._store:
            return self._store

        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                jobs = []
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
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                logger.warning("Failed to load cron store: {}", e)
                self._store = CronStore()
        else:
            self._store = CronStore()

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
        self._last_mtime = self.store_path.stat().st_mtime

    # ========== Run Log ==========

    def _append_run_record(self, record: CronRunRecord) -> None:
        """Append a run record to the per-job JSONL log."""
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._runs_dir / f"{record.job_id}.jsonl"
        entry = json.dumps({
            "jobId": record.job_id,
            "timestampMs": record.timestamp_ms,
            "durationMs": record.duration_ms,
            "status": record.status,
            "error": record.error,
        }, ensure_ascii=False)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        self._prune_run_log(log_path)

    def _prune_run_log(self, log_path: Path, max_bytes: int = 2_000_000, keep_lines: int = 2000) -> None:
        """Trim a run log file if it exceeds size limits."""
        try:
            if not log_path.exists() or log_path.stat().st_size <= max_bytes:
                return
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            if len(lines) > keep_lines:
                lines = lines[-keep_lines:]
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.warning("Cron: failed to prune run log {}: {}", log_path.name, e)

    def get_run_history(self, job_id: str, limit: int = 50) -> list[dict]:
        """Read recent run records for a job."""
        log_path = self._runs_dir / f"{job_id}.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            lines = lines[-limit:]
            return [json.loads(line) for line in lines]
        except Exception:
            return []

    # ========== Lifecycle ==========

    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._run_semaphore = asyncio.Semaphore(self.max_concurrent_runs)
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

    # ========== Scheduling ==========

    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                if job.state.next_retry_at_ms and job.state.next_retry_at_ms > now:
                    job.state.next_run_at_ms = job.state.next_retry_at_ms
                else:
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, now, job.id)

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

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """Handle timer tick - run due jobs with concurrency control."""
        self._load_store()
        if not self._store:
            return

        now = _now_ms()
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        if self._run_semaphore and len(due_jobs) > 1:
            tasks = [self._run_with_semaphore(job) for job in due_jobs]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            for job in due_jobs:
                await self._execute_job(job)

        self._save_store()
        self._arm_timer()

    async def _run_with_semaphore(self, job: CronJob) -> None:
        """Execute a job respecting the concurrency semaphore."""
        assert self._run_semaphore is not None
        async with self._run_semaphore:
            await self._execute_job(job)

    # ========== Execution ==========

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job with retry/backoff logic."""
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)

        try:
            if self.on_job:
                await self.on_job(job)

            job.state.last_status = "ok"
            job.state.last_error = None
            job.state.consecutive_errors = 0
            job.state.next_retry_at_ms = None
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            error_msg = str(e)
            job.state.last_status = "error"
            job.state.last_error = error_msg
            job.state.consecutive_errors += 1
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

        self._append_run_record(CronRunRecord(
            job_id=job.id,
            timestamp_ms=start_ms,
            duration_ms=duration_ms,
            status=job.state.last_status or "error",
            error=job.state.last_error,
        ))

        if job.state.last_status == "ok":
            self._handle_success_scheduling(job)
        # Backoff scheduling is handled in _apply_backoff

    def _apply_backoff(self, job: CronJob, error_class: str) -> None:
        """Apply retry/backoff based on error classification and job type."""
        now = _now_ms()

        if job.schedule.kind == "at":
            # One-shot: retry transient up to N times, then disable
            if error_class == "transient" and job.state.consecutive_errors <= ONE_SHOT_MAX_RETRIES:
                delay = _backoff_delay_ms(job.state.consecutive_errors - 1)
                job.state.next_retry_at_ms = now + delay
                job.state.next_run_at_ms = job.state.next_retry_at_ms
                logger.info("Cron: one-shot job '{}' will retry in {}s", job.name, delay // 1000)
            else:
                if job.delete_after_run:
                    if self._store:
                        self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
                else:
                    job.enabled = False
                    job.state.next_run_at_ms = None
                    job.state.next_retry_at_ms = None
                logger.info("Cron: one-shot job '{}' disabled after {} error", job.name, error_class)
        else:
            # Recurring: always apply backoff, job stays enabled
            if error_class == "permanent":
                job.enabled = False
                job.state.next_run_at_ms = None
                job.state.next_retry_at_ms = None
                logger.info("Cron: recurring job '{}' disabled due to permanent error", job.name)
            else:
                delay = _backoff_delay_ms(job.state.consecutive_errors - 1)
                next_normal = _compute_next_run(job.schedule, now, job.id)
                retry_at = now + delay
                # Use whichever is later: normal schedule or backoff
                if next_normal and next_normal > retry_at:
                    job.state.next_run_at_ms = next_normal
                    job.state.next_retry_at_ms = None
                else:
                    job.state.next_run_at_ms = retry_at
                    job.state.next_retry_at_ms = retry_at
                logger.info("Cron: recurring job '{}' backoff {}s", job.name, delay // 1000)

    def _handle_success_scheduling(self, job: CronJob) -> None:
        """Schedule next run after a successful execution."""
        if job.schedule.kind == "at":
            if job.delete_after_run:
                if self._store:
                    self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms(), job.id)

    # ========== Public API ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))

    def get_job(self, job_id: str) -> CronJob | None:
        """Get a single job by ID."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                return job
        return None

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
        session_target: str = "isolated",
        wake_mode: str = "now",
        delivery_mode: str | None = None,
        description: str = "",
    ) -> CronJob:
        """Add a new job."""
        store = self._load_store()
        _validate_schedule_for_add(schedule)
        now = _now_ms()
        job_id = str(uuid.uuid4())[:8]

        # Determine delivery config
        if delivery_mode:
            d_mode = delivery_mode
        elif deliver:
            d_mode = "announce"
        elif session_target == "isolated":
            d_mode = "announce"
        else:
            d_mode = "none"

        job = CronJob(
            id=job_id,
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="system_event" if session_target == "main" else "agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            delivery=DeliveryConfig(
                mode=d_mode,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now, job_id)),
            session_target=session_target,
            wake_mode=wake_mode,
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
            description=description,
        )

        store.jobs.append(job)
        self._save_store()
        self._arm_timer()

        logger.info("Cron: added job '{}' ({}) [{}]", name, job.id, session_target)
        return job

    def update_job(self, job_id: str, **patch: Any) -> CronJob | None:
        """Update fields on an existing job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id != job_id:
                continue

            if "name" in patch:
                job.name = patch["name"]
            if "message" in patch:
                job.payload.message = patch["message"]
            if "description" in patch:
                job.description = patch["description"]
            if "enabled" in patch:
                job.enabled = patch["enabled"]
            if "session_target" in patch:
                job.session_target = patch["session_target"]
            if "wake_mode" in patch:
                job.wake_mode = patch["wake_mode"]
            if "delivery_mode" in patch:
                job.delivery.mode = patch["delivery_mode"]
            if "delivery_channel" in patch:
                job.delivery.channel = patch["delivery_channel"]
            if "delivery_to" in patch:
                job.delivery.to = patch["delivery_to"]
            if "schedule" in patch and isinstance(patch["schedule"], CronSchedule):
                _validate_schedule_for_add(patch["schedule"])
                job.schedule = patch["schedule"]

            job.updated_at_ms = _now_ms()
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms(), job.id)
            self._save_store()
            self._arm_timer()
            return job
        return None

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)

        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    job.state.consecutive_errors = 0
                    job.state.next_retry_at_ms = None
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms(), job.id)
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                if not force and not job.enabled:
                    return False
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return True
        return False

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
