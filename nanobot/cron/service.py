"""Cron service for scheduling agent tasks."""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        # Fix: Return at_ms even if it is in the past (allow catch-up)
        return schedule.at_ms
    
    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms
    
    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            import datetime
            from zoneinfo import ZoneInfo
            
            base_time = datetime.datetime.fromtimestamp(now_ms / 1000, tz=datetime.timezone.utc)
            
            # If a timezone is specified in the schedule, use it for calculation
            if schedule.tz:
                try:
                    tz = ZoneInfo(schedule.tz)
                    # Convert base_time to the target timezone for cron calculation
                    local_time = base_time.astimezone(tz)
                    cron = croniter(schedule.expr, local_time)
                    next_time = cron.get_next(datetime.datetime)
                    # Convert back to UTC timestamp
                    return int(next_time.timestamp() * 1000)
                except Exception as e:
                    logger.error(f"Cron: invalid timezone '{schedule.tz}': {e}")
                    # Fallback to UTC
                    cron = croniter(schedule.expr, base_time)
                    next_time = cron.get_next(float)
                    return int(next_time * 1000)
            else:
                # Default behavior (UTC)
                cron = croniter(schedule.expr, base_time)
                next_time = cron.get_next(float)
                return int(next_time * 1000)
        except Exception as e:
            logger.error(f"Cron: failed to compute next run: {e}")
            return None
    
    return None


class CronService:
    """Service for managing and executing scheduled jobs."""
    
    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ):
        self.store_path = store_path
        self.on_job = on_job  # Callback to execute job, returns response text
        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self._running_jobs: set[str] = set()
        self._lock = asyncio.Lock()  # Protect file access
    
    def _load_store(self) -> CronStore:
        """Load jobs from disk."""
        if self._store:
            return self._store
        
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
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
                        ),
                        created_at_ms=j.get("createdAtMs", 0),
                        updated_at_ms=j.get("updatedAtMs", 0),
                        delete_after_run=j.get("deleteAfterRun", False),
                    ))
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
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
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }
        
        self.store_path.write_text(json.dumps(data, indent=2))
    
    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        
        # Start the heartbeat loop instead of single-shot timer
        self._timer_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Cron service started with {len(self._store.jobs if self._store else [])} jobs")
    
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

    async def _heartbeat_loop(self) -> None:
        """Main service loop: wake up frequently to check file changes and due jobs."""
        last_mtime = 0.0
        
        while self._running:
            try:
                # 1. Hot Reload: Check if file changed
                if self.store_path.exists():
                    current_mtime = self.store_path.stat().st_mtime
                    if current_mtime > last_mtime:
                        if last_mtime > 0: # Skip log on first run
                            logger.info("Cron: jobs.json changed, reloading...")
                        self._store = None # Force reload
                        self._load_store()
                        self._recompute_next_runs()
                        last_mtime = current_mtime
                
                # 2. Check due jobs
                await self._check_and_run_due_jobs()
                
                # 3. Smart Sleep: Sleep until next job or max 60s (for hot reload)
                sleep_time = 60
                next_wake = self._get_next_wake_ms()
                
                if next_wake:
                    delta_ms = next_wake - _now_ms()
                    delta_s = max(0.1, delta_ms / 1000)
                    sleep_time = min(60, delta_s)
                
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cron loop error: {e}")
                await asyncio.sleep(60) # Prevent busy loop on error

    async def _check_and_run_due_jobs(self) -> None:
        """Check for due jobs and execute them."""
        if not self._store:
            return
        
        now = _now_ms()
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]
        
        if due_jobs:
            logger.info(f"Cron: found {len(due_jobs)} due jobs")
            for job in due_jobs:
                if job.id in self._running_jobs:
                    logger.warning(f"Cron: job '{job.name}' ({job.id}) is already running, skipping")
                    continue
                # Run concurrently
                asyncio.create_task(self._execute_job(job))


    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        self._running_jobs.add(job.id)
        start_ms = _now_ms()
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")
        
        try:
            response = None
            if self.on_job:
                response = await self.on_job(job)
            
            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info(f"Cron: job '{job.name}' completed")
            
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron: job '{job.name}' failed: {e}")
        
        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()
        
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
        
        self._running_jobs.discard(job.id)
        self._save_store()
    
    # ========== Public API ==========
    
    async def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))
    
    async def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        kind: str = "agent_turn",
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob:
        """Add a new job."""
        jobs = await self.add_jobs_batch([
            {
                "name": name,
                "schedule": schedule,
                "message": message,
                "kind": kind,
                "deliver": deliver,
                "channel": channel,
                "to": to,
                "delete_after_run": delete_after_run
            }
        ])
        return jobs[0]

    async def add_jobs_batch(self, jobs_data: list[dict[str, Any]]) -> list[CronJob]:
        """Add multiple jobs atomically."""
        if not jobs_data:
            return []

        async with self._lock:
            store = self._load_store()
            now = _now_ms()
            new_jobs = []
    
            for data in jobs_data:
                job = CronJob(
                    id=str(uuid.uuid4())[:8],
                    name=data["name"],
                    enabled=True,
                    schedule=data["schedule"],
                    payload=CronPayload(
                        kind=data.get("kind", "agent_turn"),
                        message=data["message"],
                        deliver=data.get("deliver", False),
                        channel=data.get("channel"),
                        to=data.get("to"),
                    ),
                    state=CronJobState(next_run_at_ms=_compute_next_run(data["schedule"], now)),
                    created_at_ms=now,
                    updated_at_ms=now,
                    delete_after_run=data.get("delete_after_run", False),
                )
                new_jobs.append(job)
            
            store.jobs.extend(new_jobs)
            self._save_store()
            
            logger.info(f"Cron: added {len(new_jobs)} jobs batch")
            return new_jobs
    
    async def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        async with self._lock:
            store = self._load_store()
            before = len(store.jobs)
            store.jobs = [j for j in store.jobs if j.id != job_id]
            removed = len(store.jobs) < before
            
            if removed:
                self._save_store()
                logger.info(f"Cron: removed job {job_id}")
            
            return removed
    
    async def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        async with self._lock:
            store = self._load_store()
            for job in store.jobs:
                if job.id == job_id:
                    job.enabled = enabled
                    job.updated_at_ms = _now_ms()
                    if enabled:
                        job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                    else:
                        job.state.next_run_at_ms = None
                    self._save_store()
                    return job
            return None
    
    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job."""
        # Note: We don't lock the whole run, as it might take time.
        # But we need to load store safely.
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                if not force and not job.enabled:
                    return False
                await self._execute_job(job)
                return True
        return False
    
    async def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
