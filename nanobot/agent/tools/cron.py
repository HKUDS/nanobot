"""Cron tool for scheduling reminders and tasks."""

from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJobState, CronSchedule


class CronTool(Tool):
    """Tool to schedule reminders and recurring tasks."""

    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session context for delivery."""
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """Mark whether the tool is executing inside a cron job callback."""
        return self._in_cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """Restore previous cron context."""
        self._in_cron_context.reset(token)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "Schedule reminders and recurring tasks. Actions: add, list, remove, edit."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove", "edit"],
                    "description": "Action to perform",
                },
                "message": {"type": "string", "description": "Reminder message (for add/edit)"},
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
                },
                "tz": {
                    "type": "string",
                    "description": "IANA timezone for cron expressions (e.g. 'America/Vancouver')",
                },
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')",
                },
                "job_id": {"type": "string", "description": "Job ID (for remove/edit)"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "add":
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            return self._add_job(message, every_seconds, cron_expr, tz, at)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        elif action == "edit":
            if self._in_cron_context.get():
                return "Error: cannot edit jobs from within a cron job execution"
            return self._edit_job(job_id, message, every_seconds, cron_expr, tz, at)
        return f"Unknown action: {action}"

    def _add_job(
        self,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        if not message:
            return "Error: message is required for add"
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        # Build schedule
        delete_after = False
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
        elif at:
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        else:
            return "Error: either every_seconds, cron_expr, or at is required"

        job = self._cron.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after,
        )
        return f"Created job '{job.name}' (id: {job.id})"

    def _edit_job(
        self,
        job_id: str | None,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        if not job_id:
            return "Error: job_id is required for edit"
        
        jobs = self._cron.list_jobs()
        job = next((j for j in jobs if j.id == job_id), None)
        if not job:
            return f"Error: Job {job_id} not found"

        if not message and not every_seconds and not cron_expr and not at:
            return "Error: provide at least one field to edit (message, every_seconds, cron_expr, at)"

        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        new_message = message if message else job.payload.message
        new_schedule = job.schedule
        delete_after = job.delete_after_run

        if every_seconds or cron_expr or at:
            if every_seconds:
                new_schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
                delete_after = False
            elif cron_expr:
                new_schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
                delete_after = False
            elif at:
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(at)
                except ValueError:
                    return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
                at_ms = int(dt.timestamp() * 1000)
                new_schedule = CronSchedule(kind="at", at_ms=at_ms)
                delete_after = True

        self._cron.remove_job(job_id)
        new_job = self._cron.add_job(
            name=new_message[:30],
            schedule=new_schedule,
            message=new_message,
            deliver=True,
            channel=job.payload.channel,
            to=job.payload.to,
            delete_after_run=delete_after,
        )
        return f"Edited job '{new_job.name}' (new id: {new_job.id})"

    @staticmethod
    def _format_timing(schedule: CronSchedule) -> str:
        """Format schedule as a human-readable timing string."""
        if schedule.kind == "cron":
            tz = f" ({schedule.tz})" if schedule.tz else ""
            return f"cron: {schedule.expr}{tz}"
        if schedule.kind == "every" and schedule.every_ms:
            ms = schedule.every_ms
            if ms % 3_600_000 == 0:
                return f"every {ms // 3_600_000}h"
            if ms % 60_000 == 0:
                return f"every {ms // 60_000}m"
            if ms % 1000 == 0:
                return f"every {ms // 1000}s"
            return f"every {ms}ms"
        if schedule.kind == "at" and schedule.at_ms:
            dt = datetime.fromtimestamp(schedule.at_ms / 1000, tz=timezone.utc)
            return f"at {dt.isoformat()}"
        return schedule.kind

    @staticmethod
    def _format_state(state: CronJobState) -> list[str]:
        """Format job run state as display lines."""
        lines: list[str] = []
        if state.last_run_at_ms:
            last_dt = datetime.fromtimestamp(state.last_run_at_ms / 1000, tz=timezone.utc)
            info = f"  Last run: {last_dt.isoformat()} — {state.last_status or 'unknown'}"
            if state.last_error:
                info += f" ({state.last_error})"
            lines.append(info)
        if state.next_run_at_ms:
            next_dt = datetime.fromtimestamp(state.next_run_at_ms / 1000, tz=timezone.utc)
            lines.append(f"  Next run: {next_dt.isoformat()}")
        return lines

    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            timing = self._format_timing(j.schedule)
            parts = [f"- {j.name} (id: {j.id}, {timing})"]
            if j.payload and j.payload.message:
                parts.append(f"  Message: {j.payload.message}")
            parts.extend(self._format_state(j.state))
            lines.append("\n".join(parts))
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
