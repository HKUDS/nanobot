"""Cron tool for scheduling reminders and tasks."""

from typing import Any
import re
import time
import datetime
from zoneinfo import ZoneInfo

from nanobot.agent.tools.base import Tool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


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
        return "cron"
    
    @property
    def description(self) -> str:
        return """Schedule tasks, reminders, and timers. 
Use this for ANY request involving time.

CRITICAL - YOU MUST CHOOSE THE CORRECT TYPE:
1. 'echo' (MANDATORY for text/simple reminders): Use this for "Remind me to drink water", "Call Mom in 5 mins". It sends the text directly. FASTEST & RELIABLE.
2. 'agent' (ONLY for AI logic): Use this ONLY if you need to use tools/thinking (e.g. "Check weather every morning", "Check USD rate").

Examples:
- "Remind me to sleep in 10m" -> type='echo', message="Time to sleep!", cron_expr="in 10m"
- "Check stock price at 9am" -> type='agent', message="Check AAPL price", cron_expr="0 9 * * *"
- "Remind me every Monday" -> type='echo', message="Weekly Meeting", cron_expr="0 9 * * 1"
"""

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
                "type": {
                    "type": "string",
                    "enum": ["echo", "agent"],
                    "description": "Job type. 'echo': DIRECT MESSAGE (Mandatory for text reminders). 'agent': AI TASK (Only for thinking/tools)."
                },
                "batch": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "message": {"type": "string"},
                            "type": {"type": "string", "enum": ["echo", "agent"]},
                            "cron_expr": {"type": "string"},
                            "timezone": {"type": "string"}
                        },
                        "required": ["message"]
                    },
                    "description": "List of jobs to add at once (for batch add)"
                },
                "message": {
                    "type": "string",
                    "description": "Reminder message (for single add)"
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Schedule definition. Supports standard cron (e.g. '*/5 * * * *'), ISO timestamps for one-off, or relative time strings (e.g. 'in 5s', 'in 10m', 'in 1h')."
                },
                "timezone": {
                    "type": "string",
                    "description": "User timezone (e.g., 'Europe/Moscow'). MANDATORY if not UTC."
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
        cron_expr: str | None = None,
        timezone: str | None = None,
        job_id: str | None = None,
        type: str = "echo",
        batch: list[dict[str, Any]] | None = None,
        **kwargs: Any
    ) -> str:
        if action == "add":
            if batch:
                return await self._add_jobs_batch(batch)
            return await self._add_job(message, cron_expr, timezone, type)
        elif action == "list":
            return await self._list_jobs()
        elif action == "remove":
            return await self._remove_job(job_id)
        return f"Unknown action: {action}"

    async def _add_jobs_batch(self, batch: list[dict[str, Any]]) -> str:
        """Add multiple jobs at once."""
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        
        jobs_data = []
        for item in batch:
            msg = item.get("message", "")
            if not msg:
                continue
            
            schedule = self._build_schedule(
                item.get("cron_expr"),
                item.get("timezone")
            )
            if isinstance(schedule, str): # Error message
                return f"Error in job '{msg}': {schedule}"
            
            # Auto-delete for one-off tasks (at kind)
            delete_after = (schedule.kind == "at")

            jobs_data.append({
                "name": item.get("name", msg[:30]),
                "schedule": schedule,
                "message": msg,
                "kind": item.get("type", "echo"),
                "deliver": True,
                "channel": self._channel,
                "to": self._chat_id,
                "delete_after_run": delete_after
            })
        
        created = await self._cron.add_jobs_batch(jobs_data)
        return f"Created {len(created)} jobs successfully. I have scheduled all tasks."

    def _build_schedule(
        self,
        cron_expr: str | None,
        timezone: str | None
    ) -> CronSchedule | str:
        """Helper to build schedule object with smart parsing."""
        if not cron_expr:
            return "Error: cron_expr is required"

        cron_expr = cron_expr.strip()

        # 1. Check for relative time "in X[smh]"
        match = re.match(r"^in\s+(\d+)\s*([smh])$", cron_expr.lower())
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            seconds = amount
            if unit == 'm': seconds *= 60
            elif unit == 'h': seconds *= 3600
            
            # Calculate absolute time
            future_ms = int(time.time() * 1000) + (seconds * 1000)
            return CronSchedule(kind="at", at_ms=future_ms, tz=timezone)
        
        # 2. Check for ISO timestamp (basic check: has T and starts with digit)
        if "T" in cron_expr and cron_expr[0].isdigit():
            try:
                # Parse ISO string
                dt = datetime.datetime.fromisoformat(cron_expr)
                
                # Handle timezone if provided and dt is naive
                if timezone and (dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None):
                    tz = ZoneInfo(timezone)
                    dt = dt.replace(tzinfo=tz)
                
                # Convert to UTC timestamp
                at_ms = int(dt.timestamp() * 1000)
                return CronSchedule(kind="at", at_ms=at_ms, tz=timezone)
            except Exception as e:
                # If ISO parsing fails, might be a weird cron or error. 
                # Let's assume user meant ISO if it looks like it, so return error.
                return f"Error parsing timestamp '{cron_expr}': {e}"

        # 3. Default to Cron
        return CronSchedule(kind="cron", expr=cron_expr, tz=timezone)

    async def _add_job(
        self, 
        message: str, 
        cron_expr: str | None,
        timezone: str | None,
        type: str = "echo"
    ) -> str:
        if not message:
            return "Error: message is required for add"
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        
        schedule = self._build_schedule(cron_expr, timezone)
        if isinstance(schedule, str):
            return schedule
        
        # Auto-delete for one-off tasks
        delete_after = (schedule.kind == "at")
        
        job = await self._cron.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            kind=type,
            deliver=True,
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after
        )
        return f"Created job '{job.name}' (id: {job.id})"
    
    async def _list_jobs(self) -> str:
        jobs = await self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, schedule: {j.schedule.kind}, type: {j.payload.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)
    
    async def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        if await self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"
