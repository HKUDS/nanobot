"""Cron tool for scheduling reminders and tasks."""

from contextvars import ContextVar
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


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
        return (
            "Schedule reminders and recurring tasks. "
            "Actions: add, list, remove, update. "
            "Supports isolated sessions (default, no main-session pollution) "
            "and main sessions (system event injected into heartbeat)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove", "update"],
                    "description": "Action to perform",
                },
                "message": {"type": "string", "description": "Reminder/task message (for add/update)"},
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
                "job_id": {"type": "string", "description": "Job ID (for remove/update)"},
                "session": {
                    "type": "string",
                    "enum": ["isolated", "main"],
                    "description": "Execution mode: isolated (dedicated cron session) or main (inject into heartbeat). Default: isolated",
                },
                "wake_mode": {
                    "type": "string",
                    "enum": ["now", "next-heartbeat"],
                    "description": "When to wake (for main session). Default: now",
                },
                "delivery_mode": {
                    "type": "string",
                    "enum": ["announce", "webhook", "none"],
                    "description": "How to deliver output. Default: announce for isolated, none for main",
                },
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
        session: str = "isolated",
        wake_mode: str = "now",
        delivery_mode: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "add":
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            return self._add_job(message, every_seconds, cron_expr, tz, at, session, wake_mode, delivery_mode)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        elif action == "update":
            return self._update_job(job_id, message, delivery_mode)
        return f"Unknown action: {action}"

    def _add_job(
        self,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
        session_target: str,
        wake_mode: str,
        delivery_mode: str | None,
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

        if session_target not in ("isolated", "main"):
            return "Error: session must be 'isolated' or 'main'"

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
            session_target=session_target,
            wake_mode=wake_mode,
            delivery_mode=delivery_mode,
        )
        return f"Created job '{job.name}' (id: {job.id}, session: {session_target})"

    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs(include_disabled=True)
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            status = "enabled" if j.enabled else "disabled"
            err_info = f" [errors: {j.state.consecutive_errors}]" if j.state.consecutive_errors else ""
            lines.append(f"- {j.name} (id: {j.id}, {j.schedule.kind}, {j.session_target}, {status}{err_info})")
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"

    def _update_job(self, job_id: str | None, message: str = "", delivery_mode: str | None = None) -> str:
        if not job_id:
            return "Error: job_id is required for update"
        patch: dict[str, Any] = {}
        if message:
            patch["message"] = message
        if delivery_mode:
            patch["delivery_mode"] = delivery_mode
        if not patch:
            return "Error: nothing to update"
        result = self._cron.update_job(job_id, **patch)
        if result:
            return f"Updated job '{result.name}' ({result.id})"
        return f"Job {job_id} not found"
