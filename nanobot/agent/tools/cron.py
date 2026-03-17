"""Cron tool for scheduling reminders and tasks."""

from contextvars import ContextVar
from datetime import datetime
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule


def build_schedule(
    *,
    every_seconds: int | None = None,
    cron_expr: str | None = None,
    tz: str | None = None,
    at: str | None = None,
) -> tuple[CronSchedule, bool]:
    """Build a schedule and report whether the job should auto-delete after running."""
    if tz and not cron_expr:
        raise ValueError("tz can only be used with cron_expr")
    if tz:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(tz)
        except (KeyError, Exception):
            raise ValueError(f"unknown timezone '{tz}'") from None

    if every_seconds:
        return CronSchedule(kind="every", every_ms=every_seconds * 1000), False
    if cron_expr:
        return CronSchedule(kind="cron", expr=cron_expr, tz=tz), False
    if at:
        try:
            dt = datetime.fromisoformat(at)
        except ValueError as exc:
            raise ValueError(
                f"invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            ) from exc
        return CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000)), True
    raise ValueError("either every_seconds, cron_expr, or at is required")


def topic_jobs(cron_service: CronService, topic_session_id: str) -> list[CronJob]:
    """List jobs for a topic."""
    return [
        job
        for job in cron_service.list_jobs(include_disabled=True)
        if job.payload.topic_session_id == topic_session_id
    ]


def remove_topic_job(cron_service: CronService, topic_session_id: str, job_id: str) -> bool:
    """Remove a job only when it belongs to the topic."""
    job = next((item for item in cron_service.list_jobs(include_disabled=True) if item.id == job_id), None)
    if job is None or job.payload.topic_session_id != topic_session_id:
        return False
    return cron_service.remove_job(job_id)


def create_scoped_job(
    cron_service: CronService,
    *,
    message: str,
    channel: str,
    chat_id: str,
    schedule: CronSchedule | None = None,
    every_seconds: int | None = None,
    cron_expr: str | None = None,
    tz: str | None = None,
    at: str | None = None,
    assistant_id: str | None = None,
    topic_session_id: str | None = None,
    name: str | None = None,
    delete_after_run: bool | None = None,
) -> CronJob:
    """Create a cron job using the same behavior as the runtime tool."""
    if schedule is None:
        schedule, delete_after = build_schedule(
            every_seconds=every_seconds,
            cron_expr=cron_expr,
            tz=tz,
            at=at,
        )
    else:
        delete_after = bool(delete_after_run)
    return cron_service.add_job(
        name=(name or message)[:30],
        schedule=schedule,
        message=message,
        assistant_id=assistant_id,
        topic_session_id=topic_session_id,
        deliver=True,
        channel=channel,
        to=chat_id,
        delete_after_run=delete_after,
    )


class CronTool(Tool):
    """Tool to schedule reminders and recurring tasks."""

    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
        self._session_key = ""
        self._assistant_id = ""
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)

    def set_context(
        self,
        channel: str,
        chat_id: str,
        session_key: str | None = None,
        assistant_id: str | None = None,
    ) -> None:
        """Set the current session context for delivery."""
        self._channel = channel
        self._chat_id = chat_id
        self._session_key = session_key or ""
        self._assistant_id = assistant_id or ""

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
                "message": {"type": "string", "description": "Reminder message (for add)"},
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
                "job_id": {"type": "string", "description": "Job ID (for remove)"},
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
        try:
            job = create_scoped_job(
                self._cron,
                message=message,
                channel=self._channel,
                chat_id=self._chat_id,
                every_seconds=every_seconds,
                cron_expr=cron_expr,
                tz=tz,
                at=at,
                assistant_id=self._assistant_id or None,
                topic_session_id=self._session_key or None,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Created job '{job.name}' (id: {job.id})"

    def _list_jobs(self) -> str:
        jobs = topic_jobs(self._cron, self._session_key) if self._session_key else self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        removed = remove_topic_job(self._cron, self._session_key, job_id) if self._session_key else self._cron.remove_job(job_id)
        if removed:
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
