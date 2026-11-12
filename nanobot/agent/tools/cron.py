"""Cron tool for scheduling reminders and tasks."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.cron.service import CronService
from nanobot.cron.session_turns import is_bound_cron_job, is_cron_turn
from nanobot.cron.types import CronJob, CronJobState, CronSchedule
from nanobot.session.keys import UNIFIED_SESSION_KEY

_CRON_PARAMETERS = tool_parameters_schema(
    action=StringSchema(
        "Action to perform", enum=["add", "list", "remove", "update", "enable", "disable", "history"]
    ),
    name=StringSchema("Job label; generated from message for add if omitted."),
    message=StringSchema(
        "REQUIRED when action='add': non-empty instruction to execute when the job triggers. "
        "The final reply goes to the task's saved chat automatically. "
        "Do not copy the current channel/chat ID or require a message tool call for that reply. "
        "Include other recipients only when the user requests separate sends."
    ),
    every_seconds=IntegerSchema(
        description="Interval in seconds (for recurring tasks)", minimum=1
    ),
    cron_expr=StringSchema("Cron expression like '0 9 * * *' (for scheduled tasks)"),
    tz=StringSchema(
        "IANA timezone for cron_expr only, e.g. 'America/Vancouver'. "
        "For update, omitting tz retains the existing cron timezone."
    ),
    at=StringSchema(
        "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00'). "
        "Naive values use the tool's default timezone."
    ),
    job_id=StringSchema(
        "REQUIRED when action='remove', 'update', 'enable', 'disable', or 'history'. "
        "Job ID (obtain via action='list')."
    ),
    include_disabled=BooleanSchema(description="Include disabled jobs when action='list'."),
    limit=IntegerSchema(description="Maximum runs for action='history'; defaults to 5.", minimum=1, maximum=20),
    required=["action"],
    description=(
        "add requires exactly one schedule: every_seconds, cron_expr, or at. "
        "update changes only supplied fields and requires name, message, or one schedule."
    ),
)


@tool_parameters(_CRON_PARAMETERS)
class CronTool(Tool):
    """Tool to schedule reminders and recurring tasks."""

    def __init__(self, cron_service: CronService, default_timezone: str = "UTC"):
        self._cron = cron_service
        self._default_timezone = default_timezone

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.cron_service is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        cron_service = ctx.cron_service
        if cron_service is None:
            raise RuntimeError("CronTool requires an initialized cron service")
        return cls(cron_service=cron_service, default_timezone=ctx.timezone)

    @staticmethod
    def _request_route() -> tuple[str, str, str, dict[str, Any]]:
        """Return routing from the authoritative request snapshot."""
        ctx = current_request_context()
        if ctx is None:
            return "", "", "", {}
        raw_key = f"{ctx.channel}:{ctx.chat_id}" if ctx.channel and ctx.chat_id else ""
        session_key = (
            raw_key if ctx.session_key == UNIFIED_SESSION_KEY else (ctx.session_key or "")
        )
        return session_key, ctx.channel or "", ctx.chat_id or "", dict(ctx.metadata or {})

    @staticmethod
    def _validate_timezone(tz: str) -> str | None:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(tz)
        except (KeyError, Exception):
            return ToolResult.error(f"Error: unknown timezone '{tz}'")
        return None

    def _display_timezone(self, schedule: CronSchedule) -> str:
        """Pick the most human-meaningful timezone for display."""
        return schedule.tz or self._default_timezone

    @staticmethod
    def _format_timestamp(ms: int, tz_name: str) -> str:
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz_name))
        return f"{dt.isoformat()} ({tz_name})"

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            "Schedule reminders and recurring tasks. Actions: add, list, remove, update, enable, disable, history. "
            f"New cron schedules and naive ISO times default to {self._default_timezone}. "
            "Updates retain the existing cron timezone when tz is omitted."
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        action = params.get("action")
        if action == "add" and not str(params.get("message") or "").strip():
            errors.append("message is required when action='add'")
        if action in {"remove", "update", "enable", "disable", "history"} and not str(params.get("job_id") or "").strip():
            errors.append(f"job_id is required when action='{action}'")
        return errors

    async def execute(
        self,
        action: str,
        name: str | None = None,
        message: str | None = None,
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        include_disabled: bool = False,
        limit: int = 5,
    ) -> str:
        if action == "add":
            request = current_request_context()
            if request is not None and is_cron_turn(request.metadata):
                return ToolResult.error("Error: cannot schedule new jobs from within a cron job execution")
            return self._add_job(name, message or "", every_seconds, cron_expr, tz, at)
        elif action == "list":
            return self._list_jobs(include_disabled=include_disabled)
        elif action == "remove":
            return self._remove_job(job_id)
        elif action == "update":
            return self._update_job(job_id, name, message, every_seconds, cron_expr, tz, at)
        elif action in {"enable", "disable"}:
            return self._set_job_enabled(job_id, enabled=action == "enable")
        elif action == "history":
            return self._job_history(job_id, limit)
        return f"Unknown action: {action}"

    def _add_job(
        self,
        name: str | None,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        if not message:
            return ToolResult.error(
                "Error: cron action='add' requires a non-empty 'message' parameter "
                "describing what to do when the job triggers "
                "(e.g. the reminder text). Retry including message=\"...\"."
            )
        session_key, origin_channel, origin_chat_id, origin_metadata = self._request_route()
        if not session_key:
            return ToolResult.error("Error: scheduled cron jobs must be created from a chat session")
        if not origin_channel or not origin_chat_id:
            return ToolResult.error("Error: scheduled cron jobs must be created from a chat session")
        if cron_expr and not tz:
            tz = self._default_timezone
        schedule = self._parse_schedule(every_seconds, cron_expr, tz, at)
        if isinstance(schedule, str):
            return schedule

        job = self._cron.add_job(
            name=name or message[:30],
            schedule=schedule,
            message=message,
            delete_after_run=schedule.kind == "at",
            session_key=session_key,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            origin_metadata=origin_metadata,
        )
        return f"Created job '{job.name}' (id: {job.id})"

    def _parse_schedule(
        self, every_seconds: int | None, cron_expr: str | None,
        tz: str | None, at: str | None,
    ) -> CronSchedule | str:
        if tz and not cron_expr:
            return ToolResult.error("Error: tz can only be used with cron_expr")
        if tz:
            if err := self._validate_timezone(tz):
                return err

        schedule_count = sum(
            value is not None for value in (every_seconds, cron_expr, at)
        )
        if schedule_count != 1:
            return ToolResult.error(
                "Error: exactly one of every_seconds, cron_expr, or at is required"
            )

        if every_seconds is not None:
            if every_seconds <= 0:
                return ToolResult.error("Error: every_seconds must be a positive integer")
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
        elif at:
            from zoneinfo import ZoneInfo

            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return ToolResult.error(f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS")
            if dt.tzinfo is None:
                if err := self._validate_timezone(self._default_timezone):
                    return err
                dt = dt.replace(tzinfo=ZoneInfo(self._default_timezone))
            at_ms = int(dt.timestamp() * 1000)
            if at_ms <= int(time.time() * 1000):
                return ToolResult.error(
                    f"Error: one-time job time '{at}' is not in the future. "
                    "Retry with a future ISO datetime computed from the current time."
                )
            schedule = CronSchedule(kind="at", at_ms=at_ms)
        else:
            return ToolResult.error("Error: either every_seconds, cron_expr, or at is required")

        return schedule

    def _update_job(
        self, job_id: str | None, name: str | None, message: str | None,
        every_seconds: int | None, cron_expr: str | None, tz: str | None, at: str | None,
    ) -> str:
        if not job_id:
            return ToolResult.error("Error: job_id is required for update")
        if all(value is None for value in (name, message, every_seconds, cron_expr, tz, at)):
            return ToolResult.error("Error: update requires at least one changed field")
        for field, value in (("name", name), ("message", message)):
            if value is not None and not value.strip():
                return ToolResult.error(f"Error: {field} must not be empty")
        job = self._cron.get_job(job_id)
        if job is None:
            return ToolResult.error(f"Error: job {job_id} not found")
        schedule = None
        if any(value is not None for value in (every_seconds, cron_expr, tz, at)):
            if cron_expr and not tz:
                tz = job.schedule.tz if job.schedule.kind == "cron" else self._default_timezone
            schedule = self._parse_schedule(every_seconds, cron_expr, tz, at)
            if isinstance(schedule, str):
                return schedule
        try:
            result = self._cron.update_job(job_id, name=name, message=message, schedule=schedule)
        except ValueError as exc:
            return ToolResult.error(f"Error: {exc}")
        if result == "protected":
            return ToolResult.error("Error: system-managed cron jobs are protected")
        if result == "not_found":
            return ToolResult.error(f"Error: job {job_id} not found")
        return f"Updated job '{result.name}' (id: {result.id})"

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

    def _list_jobs(self, include_disabled: bool = False) -> str:
        jobs = self._cron.list_jobs(include_disabled=include_disabled)
        if not jobs:
            return "No scheduled jobs."
        lines: list[str] = []
        for j in jobs:
            timing = self._format_timing(j.schedule)
            parts = [f"- {j.name} (id: {j.id}, {timing})"]
            if include_disabled:
                parts.append(f"  Status: {'enabled' if j.enabled else 'disabled'}")
            if j.payload.kind == "system_event":
                parts.append(f"  Purpose: {self._system_job_purpose(j)}")
                parts.append("  Protected: visible for inspection, but cannot be removed.")
            parts.extend(self._format_state(j.state, j.schedule))
            lines.append("\n".join(parts))
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _set_job_enabled(self, job_id: str | None, *, enabled: bool) -> str:
        if not job_id:
            return ToolResult.error("Error: job_id is required for enable or disable")
        job = self._cron.get_job(job_id)
        if job is None:
            return ToolResult.error(f"Error: job {job_id} not found")
        if job.payload.kind == "system_event":
            return ToolResult.error("Error: system-managed cron jobs are protected; change their configuration instead")
        if enabled and not is_bound_cron_job(job):
            return ToolResult.error("Error: job has no linked chat; recreate it from a chat session")
        self._cron.enable_job(job_id, enabled=enabled)
        return f"{'Enabled' if enabled else 'Disabled'} job {job_id}"

    def _job_history(self, job_id: str | None, limit: int) -> str:
        if not job_id:
            return ToolResult.error("Error: job_id is required for history")
        job = self._cron.get_job(job_id)
        if job is None:
            return ToolResult.error(f"Error: job {job_id} not found")
        if not job.state.run_history:
            return f"No recorded runs for job {job_id}."
        lines = [f"Recent runs for '{job.name}' (id: {job.id}), newest first:"]
        display_tz = self._display_timezone(job.schedule)
        for run in reversed(job.state.run_history[-limit:]):
            timestamp = self._format_timestamp(run.run_at_ms, display_tz)
            lines.append(f"- {timestamp} — {run.status} ({run.duration_ms}ms)")
            if run.error:
                lines.append(f"  Error: {run.error}")
        return "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return ToolResult.error("Error: job_id is required for remove")
        result = self._cron.remove_job(job_id)
        if result == "removed":
            return f"Removed job {job_id}"
        if result == "protected":
            job = self._cron.get_job(job_id)
            if job and job.name == "dream":
                return (
                    "Cannot remove job `dream`.\n"
                    "This is a system-managed Dream memory consolidation job for long-term memory.\n"
                    "It remains visible so you can inspect it, but it cannot be removed."
                )
            return (
                f"Cannot remove job `{job_id}`.\n"
                "This is a protected system-managed cron job."
            )
        return f"Job {job_id} not found"
