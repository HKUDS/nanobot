"""SchedulerActor: Pulsing actor for cron job scheduling."""

import asyncio
from pathlib import Path
from typing import Any

import pulsing as pul
from loguru import logger

from nanobot.cron.service import CronStoreService, now_ms
from nanobot.cron.types import CronJob, CronSchedule


@pul.remote
class SchedulerActor:
    """
    Cron scheduler actor.

    Manages periodic and one-shot jobs, resolving AgentActor via Pulsing
    for execution and channel actors for delivery (p2p by name).

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

        self._service = CronStoreService(cron_store_path)
        self._timer_task: asyncio.Task | None = None
        self._running = False

    # ========== Lifecycle (Pulsing hooks) ==========

    async def on_start(self, actor_id: Any = None) -> None:
        """Pulsing lifecycle hook: called automatically after spawn."""
        self._running = True
        self._service.load()
        self._service.recompute_next_runs()
        self._service.save()
        self._arm_timer()

        job_count = len(self._service.load().jobs)
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

    def _get_next_wake_ms(self) -> int | None:
        return self._service.next_wake_at_ms()

    def _arm_timer(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        due_jobs = self._service.due_jobs()

        for job in due_jobs:
            await self._execute_job(job)

        self._service.save()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        start_ms = now_ms()
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
                    from nanobot.channels.manager import get_channel_actor

                    ch = await get_channel_actor(job.payload.channel)
                    await ch.send_text(job.payload.to, response or "")
                except Exception as e:
                    logger.warning(
                        f"Cron: could not deliver to channel.{job.payload.channel}: {e}"
                    )

            logger.info(f"Cron: job '{job.name}' completed")
            self._service.mark_job_finished(job, ok=True, started_at_ms=start_ms)

        except Exception as e:
            logger.error(f"Cron: job '{job.name}' failed: {e}")
            self._service.mark_job_finished(job, ok=False, error=str(e), started_at_ms=start_ms)

    # ========== Public API (cron management) ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        return self._service.list_jobs(include_disabled=include_disabled)

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
        job = self._service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            channel=channel,
            to=to,
            delete_after_run=delete_after_run,
        )
        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id})")
        return job

    def remove_job(self, job_id: str) -> bool:
        removed = self._service.remove_job(job_id)
        if removed:
            self._arm_timer()
            logger.info(f"Cron: removed job {job_id}")
        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        job = self._service.enable_job(job_id, enabled=enabled)
        if job:
            self._arm_timer()
        return job

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        job = self._service.get_job(job_id)
        if not job:
            return False
        if not force and not job.enabled:
            return False
        await self._execute_job(job)
        self._service.save()
        self._arm_timer()
        return True

    def status(self) -> dict:
        return {
            "enabled": self._running,
            "jobs": len(self._service.load().jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
