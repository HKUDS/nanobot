"""SchedulerActor: Pulsing actor for cron job scheduling."""

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import pulsing as pul
from loguru import logger

from nanobot.cron.types import (
    CronJob,
    CronJobState,
    CronPayload,
    CronSchedule,
    CronStore,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter

            cron = croniter(schedule.expr, time.time())
            next_time = cron.get_next()
            return int(next_time * 1000)
        except Exception:
            return None

    return None


@pul.remote
class SchedulerActor:
    """
    Cron scheduler actor.

    Manages periodic and one-shot jobs, resolving AgentActor via Pulsing
    for execution and ChannelActor for delivery -- pure point-to-point.

    Heartbeat is NOT built in; if you need periodic HEARTBEAT.md checking,
    register it as a normal cron job via CronTool or ``add_job()``.
    """

    def __init__(
        self,
        cron_store_path: Path,
        workspace: Path,
        agent_name: str = "agent",
    ):
        self.cron_store_path = cron_store_path
        self.workspace = workspace
        self.agent_name = agent_name

        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False

    # ========== Lifecycle (Pulsing hooks) ==========

    async def on_start(self, actor_id: Any = None) -> None:
        """Pulsing lifecycle hook: called automatically after spawn."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()

        job_count = len(self._store.jobs) if self._store else 0
        logger.info(f"SchedulerActor started: {job_count} cron jobs")

    async def on_stop(self) -> None:
        """Pulsing lifecycle hook: called before actor shutdown."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    # ========== Agent resolution ==========

    async def _call_agent(
        self, channel: str, sender_id: str, chat_id: str, content: str
    ) -> str:
        """Resolve AgentActor and process a message."""
        from nanobot.actor.agent import AgentActor

        agent = await AgentActor.resolve(self.agent_name)
        return await agent.process(
            channel=channel,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
        )

    # ========== Cron internals ==========

    def _load_store(self) -> CronStore:
        """Load jobs from disk (Pydantic handles all JSON ↔ model mapping)."""
        if self._store:
            return self._store

        if self.cron_store_path.exists():
            try:
                self._store = CronStore.model_validate_json(
                    self.cron_store_path.read_text()
                )
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
                self._store = CronStore()
        else:
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """Save jobs to disk (Pydantic handles all model → JSON mapping)."""
        if not self._store:
            return
        self.cron_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.cron_store_path.write_text(
            self._store.model_dump_json(by_alias=True, indent=2)
        )

    def _recompute_next_runs(self) -> None:
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)

    def _get_next_wake_ms(self) -> int | None:
        if not self._store:
            return None
        times = [
            j.state.next_run_at_ms
            for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms
        ]
        return min(times) if times else None

    def _arm_timer(self) -> None:
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
        if not self._store:
            return

        now = _now_ms()
        due_jobs = [
            j
            for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        for job in due_jobs:
            await self._execute_job(job)

        self._save_store()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        start_ms = _now_ms()
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")

        try:
            channel = job.payload.channel or "cli"
            chat_id = job.payload.to or "direct"

            response = await self._call_agent(
                channel=channel,
                sender_id="cron",
                chat_id=chat_id,
                content=job.payload.message,
            )

            # Point-to-point delivery: resolve channel actor by name
            if job.payload.deliver and job.payload.to and job.payload.channel:
                try:
                    from nanobot.actor.channel import ChannelActor

                    ch = await ChannelActor.resolve(f"channel.{job.payload.channel}")
                    await ch.send_text(job.payload.to, response or "")
                except Exception as e:
                    logger.warning(
                        f"Cron: could not deliver to channel.{job.payload.channel}: {e}"
                    )

            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info(f"Cron: job '{job.name}' completed")

        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron: job '{job.name}' failed: {e}")

        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()

        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    # ========== Public API (cron management) ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float("inf"))

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
        store = self._load_store()
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

        store.jobs.append(job)
        self._save_store()
        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id})")
        return job

    def remove_job(self, job_id: str) -> bool:
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before
        if removed:
            self._save_store()
            self._arm_timer()
            logger.info(f"Cron: removed job {job_id}")
        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    job.state.next_run_at_ms = _compute_next_run(
                        job.schedule, _now_ms()
                    )
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
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

    def status(self) -> dict:
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
