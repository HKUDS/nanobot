"""Cron tool for scheduling reminders and tasks."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
from nanobot.i18n import _


class CronTool(Tool):
    """Tool to schedule reminders and recurring tasks."""
    
    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session context for delivery."""
        self._channel = channel
        self._chat_id = chat_id
    
    @property
    def name(self) -> str:
        return _("tools.cron.name")
    
    @property
    def description(self) -> str:
        return _("tools.cron.description")
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "Action to perform"
                },
                "message": {
                    "type": "string",
                    "description": "Reminder message (for add)"
                },
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)"
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)"
                },
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')"
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID (for remove)"
                }
            },
            "required": ["action"]
        }
    
    async def execute(
        self,
        action: str,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        **kwargs: Any
    ) -> str:
        if action == "add":
            return self._add_job(message, every_seconds, cron_expr, at)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        return _("tools.cron.error_action_required")
    
    def _add_job(self, message: str, every_seconds: int | None, cron_expr: str | None, at: str | None) -> str:
        if not message:
            return _("tools.cron.error_message_required")
        if not self._channel or not self._chat_id:
            return _("tools.cron.error_no_session")
        
        delete_after = False
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr)
        elif at:
            from datetime import datetime
            dt = datetime.fromisoformat(at)
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        else:
            return _("tools.cron.error_schedule_required")
        
        job = self._cron.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after,
        )
        return _("tools.cron.job_created", name=job.name, id=job.id)
    
    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return _("tools.cron.no_jobs")
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return _("tools.cron.scheduled_jobs") + "\n" + "\n".join(lines)
    
    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return _("tools.cron.error_job_id_required")
        if self._cron.remove_job(job_id):
            return _("tools.cron.job_removed", id=job_id)
        return _("tools.cron.job_not_found", id=job_id)
