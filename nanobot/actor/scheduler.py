"""SchedulerActor: cron jobs via Pulsing delayed call per job."""

import time
from pathlib import Path
from typing import Any

import pulsing as pul
from loguru import logger

from nanobot.cron.service import CronStoreService, compute_next_run, now_ms


@pul.remote
class SchedulerActor:
    def __init__(
        self,
        cron_store_path: Path,
        workspace: Path,
        agent_name: str = "agent",
        scheduler_name: str = "scheduler",
    ):
        self.cron_store_path = cron_store_path
        self.workspace = workspace
        self.agent_name = agent_name
        self._name = scheduler_name

        self._service = CronStoreService(cron_store_path)
        self._job_tasks: dict[str, Any] = {}
        self._running = False

    async def on_start(self, actor_id: Any = None) -> None:
        self._running = True
        store = self._service.load()
        base = now_ms()
        for job in store["jobs"]:
            if not job.get("enabled", True):
                continue
            state = job.setdefault("state", {})
            n = state.get("next_run_at_ms")
            if not n or n < base:
                state["next_run_at_ms"] = compute_next_run(job.get("schedule", {}), base)
            if state.get("next_run_at_ms"):
                self._schedule_job(job)
        self._service.save()
        logger.info(f"SchedulerActor started: {len(store['jobs'])} cron jobs")

    async def on_stop(self) -> None:
        self._running = False
        for task in self._job_tasks.values():
            task.cancel()
        self._job_tasks.clear()

    def _schedule_job(self, job: dict) -> None:
        jid = job.get("id")
        n = (job.get("state") or {}).get("next_run_at_ms")
        if not self._running or not job.get("enabled", True) or not n:
            return
        if jid in self._job_tasks:
            self._job_tasks[jid].cancel()
            del self._job_tasks[jid]
        delay = max(0.0, n / 1000.0 - time.time())
        self._job_tasks[jid] = self.delayed(delay).run_scheduled_job(jid)

    async def run_scheduled_job(self, job_id: str) -> None:
        self._job_tasks.pop(job_id, None)
        job = self._service.get_job(job_id)
        if not job or not job.get("enabled", True):
            return
        await self._execute_job(job)
        self._service.save()
        job = self._service.get_job(job_id)
        if job and (job.get("state") or {}).get("next_run_at_ms"):
            self._schedule_job(job)

    async def _execute_job(self, job: dict) -> None:
        start_ms = now_ms()
        name, jid = job.get("name", ""), job.get("id", "")
        payload = job.get("payload", {})
        logger.info(f"Cron: executing job '{name}' ({jid})")
        try:
            from nanobot.actor.agent import AgentActor

            agent = await AgentActor.resolve(self.agent_name)
            response = await agent.process(
                channel=payload.get("channel") or "cli",
                sender_id="cron",
                chat_id=payload.get("to") or "direct",
                content=payload.get("message", ""),
            )
            if payload.get("deliver") and payload.get("to") and payload.get("channel"):
                try:
                    ch = (await pul.resolve(f"channel.{payload['channel']}")).as_any()
                    await ch.send_text(payload["to"], response or "")
                except Exception as e:
                    logger.warning(f"Cron: could not deliver to channel.{payload['channel']}: {e}")

            logger.info(f"Cron: job '{name}' completed")
            self._service.mark_job_finished(job, ok=True, started_at_ms=start_ms)

        except Exception as e:
            logger.error(f"Cron: job '{name}' failed: {e}")
            self._service.mark_job_finished(job, ok=False, error=str(e), started_at_ms=start_ms)

    def list_jobs(self, include_disabled: bool = False) -> list[dict]:
        return self._service.list_jobs(include_disabled=include_disabled)

    def add_job(
        self,
        name: str,
        schedule: dict,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> dict:
        job = self._service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            channel=channel,
            to=to,
            delete_after_run=delete_after_run,
        )
        self._schedule_job(job)
        logger.info(f"Cron: added job '{name}' ({job['id']})")
        return job

    def remove_job(self, job_id: str) -> bool:
        if job_id in self._job_tasks:
            self._job_tasks[job_id].cancel()
            del self._job_tasks[job_id]
        removed = self._service.remove_job(job_id)
        if removed:
            logger.info(f"Cron: removed job {job_id}")
        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> dict | None:
        job = self._service.enable_job(job_id, enabled=enabled)
        if job:
            if enabled:
                self._schedule_job(job)
            elif job_id in self._job_tasks:
                self._job_tasks[job_id].cancel()
                del self._job_tasks[job_id]
        return job

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        job = self._service.get_job(job_id)
        if not job:
            return False
        if not force and not job.get("enabled", True):
            return False
        await self._execute_job(job)
        self._service.save()
        job = self._service.get_job(job_id)
        if job and (job.get("state") or {}).get("next_run_at_ms"):
            self._schedule_job(job)
        return True

    def status(self) -> dict:
        store = self._service.load()
        next_runs = [
            (j.get("state") or {}).get("next_run_at_ms")
            for j in store["jobs"]
            if j.get("enabled", True) and (j.get("state") or {}).get("next_run_at_ms")
        ]
        return {
            "enabled": self._running,
            "jobs": len(store["jobs"]),
            "next_wake_at_ms": min(next_runs) if next_runs else None,
        }
