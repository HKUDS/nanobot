"""Cron tool for scheduling reminders and tasks."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from typing import Any

from blackcat.agent.tools.base import Tool, tool_parameters
from blackcat.agent.tools.context import ContextAware, RequestContext
from blackcat.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from blackcat.cron.service import CronService
from blackcat.cron.types import CronJob, CronJobState, CronSchedule

_CRON_PARAMETERS = tool_parameters_schema(
    action=StringSchema("Action to perform", enum=["add", "list", "remove", "update", "pause", "resume"]),
    name=StringSchema(
        "Optional short human-readable label for the job "
        "(e.g., 'weather-monitor', 'daily-standup'). Defaults to first 30 chars of message."
    ),
    message=StringSchema(
        "REQUIRED when action='add'. Instruction for the agent to execute when the job triggers "
        "(e.g., 'Send a reminder to WeChat: xxx' or 'Check system status and report'). "
        "Not used for action='list' or action='remove'."
    ),
    every_seconds=IntegerSchema(0, description="Interval in seconds (for recurring tasks)"),
    cron_expr=StringSchema("Cron expression like '0 9 * * *' (for scheduled tasks)"),
    tz=StringSchema(
        "Optional IANA timezone for cron expressions (e.g. 'America/Vancouver'). "
        "When omitted with cron_expr, the tool's default timezone applies."
    ),
    at=StringSchema(
        "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00'). "
        "Naive values use the tool's default timezone."
    ),
    deliver=BooleanSchema(
        description="Whether to deliver the execution result to the user channel (default true)",
        default=True,
    ),
    job_id=StringSchema("REQUIRED when action='remove'. Job ID to remove (obtain via action='list')."),
    required=["action"],
    description=(
        "Action-specific parameters: add requires a non-empty message plus one schedule "
        "(every_seconds, cron_expr, or at); remove requires job_id; list only needs action. "
        "Per-action requirements are enforced at runtime (see field descriptions) so the "
        "top-level schema stays compatible with providers (e.g. OpenAI Codex/Responses) that "
        "reject oneOf/anyOf/allOf/enum/not at the root of function parameters."
    ),
)


@tool_parameters(_CRON_PARAMETERS)
class CronTool(Tool, ContextAware):
    """Tool to schedule reminders and recurring tasks."""

    def __init__(self, cron_service: CronService, default_timezone: str = "UTC"):
        self._cron = cron_service
        self._default_timezone = default_timezone
        self._channel: ContextVar[str] = ContextVar("cron_channel", default="")
        self._chat_id: ContextVar[str] = ContextVar("cron_chat_id", default="")
        self._metadata: ContextVar[dict] = ContextVar("cron_metadata", default={})
        self._session_key: ContextVar[str] = ContextVar("cron_session_key", default="")
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.cron_service is not None

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(cron_service=ctx.cron_service, default_timezone=ctx.timezone)

    def set_context(self, ctx: RequestContext) -> None:
        """Set the current session context for delivery."""
        self._channel.set(ctx.channel)
        self._chat_id.set(ctx.chat_id)
        self._metadata.set(ctx.metadata)
        self._session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")

    def set_cron_context(self, active: bool):
        """Mark whether the tool is executing inside a cron job callback."""
        return self._in_cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """Restore previous cron context."""
        self._in_cron_context.reset(token)

    @staticmethod
    def _validate_timezone(tz: str) -> str | None:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(tz)
        except (KeyError, Exception):
            return f"Error: unknown timezone '{tz}'"
        return None

    def _display_timezone(self, schedule: CronSchedule) -> str:
        """Pick the most human-meaningful timezone for display."""
        return schedule.tz or self._default_timezone

    @staticmethod
    def _format_timestamp(ms: int, tz_name: str) -> str:
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz_name))
        return f"{dt.isoformat()} ({tz_name})"

    @staticmethod
    def _encode_tool_message(message: str, tool_name: str) -> str:
        """Encode a message as a tool call JSON payload."""
        import json
        return json.dumps({"tool_name": tool_name, "message": message})

    @staticmethod
    def _safe_metadata(metadata: dict | None) -> dict:
        """Ensure metadata is a safe dict (defensive copy)."""
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            return {}
        return dict(metadata)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            f"Schedule reminders and recurring tasks. Actions: add, list, remove, update, pause, resume. "
            f"If tz is omitted, cron expressions and naive ISO times default to {self._default_timezone}."
        )

    @property
    def parameters(self) -> dict:
        # Delegate to the schema defined by @tool_parameters decorator
        # This ensures consistency between runtime validation and LLM schema
        return _CRON_PARAMETERS

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        action = params.get("action")
        if action == "add" and not str(params.get("message") or "").strip():
            errors.append("message is required when action='add'")
        if action == "remove" and not str(params.get("job_id") or "").strip():
            errors.append("job_id is required when action='remove'")
        return errors

    async def execute(
        self,
        action: str,
        name: str | None = None,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        deliver: bool = True,
        tool_name: str | None = None,
        metadata: dict | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "add":
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            return self._add_job(name, message, every_seconds, cron_expr, tz, at, tool_name, metadata)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        elif action == "update":
            return self._update_job(job_id, message, every_seconds, cron_expr, tz, at, tool_name, metadata)
        elif action == "pause":
            return self._pause_job(job_id)
        elif action == "resume":
            return self._resume_job(job_id)
        return f"Unknown action: {action}"

    def _build_schedule(
        self,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> tuple[CronSchedule, bool]:
        """Build a CronSchedule from parameters. Returns (schedule, delete_after_run)."""
        if tz and not cron_expr:
            raise ValueError("tz can only be used with cron_expr")
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except (KeyError, Exception) as e:
                raise ValueError(f"unknown timezone '{tz}'") from e

        delete_after = False
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz or self._default_timezone)
        elif at:
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(at)
            # Apply default timezone if naive datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(self._default_timezone))
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        else:
            raise ValueError("either every_seconds, cron_expr, or at is required")

        return schedule, delete_after

    def _add_job(
        self,
        name: str | None,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
        tool_name: str | None,
        metadata: dict | None,
    ) -> str:
        if not message and not tool_name:
            return "Error: action='add' requires a non-empty 'message' (or 'tool_name'). Retry including message='...' in your request."

        channel = self._channel.get()
        chat_id = self._chat_id.get()
        if not channel or not chat_id:
            return "Error: no session context (channel/chat_id)"

        try:
            schedule, delete_after = self._build_schedule(every_seconds, cron_expr, tz, at)
        except ValueError as e:
            return f"Error: {e}"

        # Encode tool execution if specified
        job_message = self._encode_tool_message(message, tool_name) if tool_name else message

        # Build metadata with internal flags
        job_metadata = self._safe_metadata(metadata)
        job_metadata["_paused"] = False
        if tool_name:
            job_metadata["_tool_name"] = tool_name

        job = self._cron.add_job(
            name=name or (message[:30] if message else (tool_name or "untitled")),
            schedule=schedule,
            message=job_message,
            deliver=True,
            channel=channel,
            to=chat_id,
            channel_meta=self._metadata.get() or None,
            session_key=self._session_key.get() or None,
            delete_after_run=delete_after,
            metadata=job_metadata,
        )

        tool_info = f" → execute {tool_name}" if tool_name else ""
        return f"Created job '{job.name}' (id: {job.id}){tool_info}"

    def _format_timing(self, schedule: CronSchedule) -> str:
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
            return f"at {self._format_timestamp(schedule.at_ms, self._display_timezone(schedule))}"
        return schedule.kind

    def _require_job(
        self, job_id: str | None, action: str
    ) -> tuple[CronJob, None] | tuple[None, str]:
        """Fetch a job or return an error. Returns (job, None) or (None, error_message)."""
        if not job_id or job_id is None:
            return None, f"Error: job_id is required for {action}"
        job = self._cron.get_job(job_id)
        if not job:
            return None, f"Job {job_id} not found"
        return job, None

    def _format_state(self, state: CronJobState, schedule: CronSchedule) -> list[str]:
        """Format job run state as display lines."""
        lines: list[str] = []
        display_tz = self._display_timezone(schedule)
        if state.last_run_at_ms:
            info = (
                f"  Last run: {self._format_timestamp(state.last_run_at_ms, display_tz)}"
                f" — {state.last_status or 'unknown'}"
            )
            if state.last_error:
                info += f" ({state.last_error})"
            lines.append(info)
        if state.next_run_at_ms:
            lines.append(f"  Next run: {self._format_timestamp(state.next_run_at_ms, display_tz)}")
        return lines

    @staticmethod
    def _system_job_purpose(job: CronJob) -> str:
        if job.name == "dream":
            return "Dream memory consolidation for long-term memory."
        return "System-managed internal job."

    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            timing = self._format_timing(j.schedule)
            parts = [f"- {j.name} (id: {j.id}, {timing})"]
            if j.payload.kind == "system_event":
                parts.append(f"  Purpose: {self._system_job_purpose(j)}")
                parts.append("  Protected: visible for inspection, but cannot be removed.")
            parts.extend(self._format_state(j.state, j.schedule))
            lines.append("\n".join(parts))
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"

        # Check for protected system jobs first
        job = self._cron.get_job(job_id)
        if job and job.name == "dream":
            return (
                "Cannot remove job `dream`.\n"
                "This is a system-managed Dream memory consolidation job for long-term memory.\n"
                "It remains visible so you can inspect it, but it cannot be removed."
            )

        result = self._cron.remove_job(job_id)
        if result:
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"

    def _update_job(
        self,
        job_id: str | None,
        message: str | None,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
        tool_name: str | None,
        metadata: dict | None,
    ) -> str:
        """Update an existing job. Only specified fields are changed."""
        job, error = self._require_job(job_id, "update")
        if error:
            return error

        if job is not None and job_id is not None:
            # Build new schedule if any timing params provided
            new_schedule = None
            delete_after = job.delete_after_run
            if any(p is not None for p in [every_seconds, cron_expr, at]):
                try:
                    new_schedule, delete_after = self._build_schedule(every_seconds, cron_expr, tz, at)
                except ValueError as e:
                    return f"Error: {e}"

            # Update message (preserve tool encoding if applicable)
            new_message = job.payload.message if job.payload else ""

            # Update metadata
            new_metadata = self._safe_metadata(job.metadata)
            if metadata:
                new_metadata.update(metadata)
            if tool_name:
                new_metadata["_tool_name"] = tool_name
            # Preserve pause state
            if job.metadata and "_paused" in job.metadata:
                new_metadata["_paused"] = job.metadata["_paused"]

            # Remove old and add new (since CronService likely doesn't support true updates)
            self._cron.remove_job(job_id)
            new_job = self._cron.add_job(
                name=job.name,
                schedule=new_schedule or job.schedule,
                message=new_message,
                deliver=job.payload.deliver,
                channel=job.payload.channel,
                to=job.payload.to,
                delete_after_run=delete_after,
                metadata=new_metadata,
            )

            return f"Updated job (new id: {new_job.id})"
        else:
            return "No job to update"

    def _pause_job(self, job_id: str | None) -> str:
        """Pause a job without removing it."""
        job, error = self._require_job(job_id, "pause")
        if error:
            return error

        if job_id is not None and job is not None:
            # Get current metadata and add paused flag
            metadata = self._safe_metadata(job.metadata)
            metadata["_paused"] = True

            # Update via remove/add pattern (CronService doesn't have metadata update)
            self._cron.remove_job(job_id)
            new_job = self._cron.add_job(
                name=job.name,
                schedule=job.schedule,
                message=job.payload.message if job.payload else "",
                deliver=job.payload.deliver if job.payload else True,
                channel=job.payload.channel if job.payload else "",
                to=job.payload.to if job.payload else "",
                delete_after_run=job.delete_after_run,
                metadata=metadata,
            )
            return f"Paused job {job_id} (id: {new_job.id})"
        else:
            return "No job to pause"

    def _resume_job(self, job_id: str | None) -> str:
        """Resume a paused job."""
        job, error = self._require_job(job_id, "resume")
        if error:
            return error

        if job is not None and job_id is not None:
            # Get current metadata and remove paused flag
            metadata = self._safe_metadata(job.metadata)
            metadata["_paused"] = False

            # Update via remove/add pattern
            self._cron.remove_job(job_id)
            new_job = self._cron.add_job(
                name=job.name,
                schedule=job.schedule,
                message=job.payload.message if job.payload else "",
                deliver=job.payload.deliver if job.payload else True,
                channel=job.payload.channel if job.payload else "",
                to=job.payload.to if job.payload else "",
                delete_after_run=job.delete_after_run,
                metadata=metadata,
            )
            return f"Resumed job {job_id} (id: {new_job.id})"
        else:
            return "No job to resume"
