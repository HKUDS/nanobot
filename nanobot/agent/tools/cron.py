"""Cron tool for scheduling reminders and tasks.

Resolves SchedulerActor via Pulsing name -- no object reference needed.
"""

from typing import Any

from nanobot.agent.tools.base import Tool, ToolContext
from nanobot.cron.types import CronSchedule


class CronTool(Tool):
    """Tool to schedule reminders and recurring tasks.

    Resolves SchedulerActor by Pulsing name for pure point-to-point
    communication -- no object references passed in.
    """

    def __init__(self, scheduler_name: str = "scheduler"):
        self._scheduler_name = scheduler_name

    async def _get_scheduler(self):
        """Resolve the SchedulerActor via Pulsing."""
        from nanobot.actor.scheduler import SchedulerActor

        return await SchedulerActor.resolve(self._scheduler_name)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "Schedule reminders and recurring tasks. Actions: add, list, remove."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "Action to perform",
                },
                "message": {
                    "type": "string",
                    "description": "Reminder message (for add)",
                },
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID (for remove)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        ctx: ToolContext,
        action: str,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "add":
            return await self._add_job(ctx, message, every_seconds, cron_expr)
        elif action == "list":
            return await self._list_jobs()
        elif action == "remove":
            return await self._remove_job(job_id)
        return f"Unknown action: {action}"

    async def _add_job(
        self,
        ctx: ToolContext,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
    ) -> str:
        if not message:
            return "Error: message is required for add"
        if not ctx.channel or not ctx.chat_id:
            return "Error: no session context (channel/chat_id)"

        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr)
        else:
            return "Error: either every_seconds or cron_expr is required"

        scheduler = await self._get_scheduler()
        job = scheduler.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=ctx.channel,
            to=ctx.chat_id,
        )
        return f"Created job '{job.name}' (id: {job.id})"

    async def _list_jobs(self) -> str:
        scheduler = await self._get_scheduler()
        jobs = scheduler.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    async def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        scheduler = await self._get_scheduler()
        if scheduler.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
