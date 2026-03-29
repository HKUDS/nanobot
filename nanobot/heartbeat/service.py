"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Literal

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


@dataclass
class DueTask:
    name: str
    task_type: Literal["announcement", "system", "reminder"]
    schedule: str | None  # None for announcements


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): when last_run_tracking=True, deterministically computes
    which tasks are due without an LLM call. Falls back to LLM when disabled.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
        last_run_tracking: bool = False,
        timezone: str | None = None,
        suppress_errors: bool = False,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.last_run_tracking = last_run_tracking
        self.timezone = timezone
        self.suppress_errors = suppress_errors
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    @staticmethod
    def _compute_due_tasks(content: str, now: datetime) -> list[DueTask]:
        """Deterministically compute which tasks are due now.

        Returns a list of DueTask covering three types:
        - announcement: any ### entry under ## Announcements (always due)
        - system: Type: system task whose Schedule has passed
        - reminder: user reminder task whose Schedule has passed
        """
        due: list[DueTask] = []

        # 1. Announcements — always due if any ### entries exist
        ann_match = re.search(r"^## Announcements\s*$", content, re.MULTILINE)
        if ann_match:
            ann_start = ann_match.end()
            next_sec = re.search(r"^## ", content[ann_start:], re.MULTILINE)
            ann_end = ann_start + next_sec.start() if next_sec else len(content)
            for m in re.finditer(r"^###\s+(.+)", content[ann_start:ann_end], re.MULTILINE):
                due.append(DueTask(name=m.group(1).strip(), task_type="announcement", schedule=None))

        # 2. User Tasks — due if now >= Schedule
        user_match = re.search(r"^## User Tasks\s*$", content, re.MULTILINE)
        if not user_match:
            return due

        section_start = user_match.end()
        next_sec = re.search(r"^## ", content[section_start:], re.MULTILINE)
        section_end = section_start + next_sec.start() if next_sec else len(content)
        section = content[section_start:section_end]

        for block in re.split(r"\n(?=###\s)", section):
            block = block.strip()
            if not block.startswith("###"):
                continue

            name_match = re.match(r"###\s+(.+)", block)
            if not name_match:
                continue
            task_name = name_match.group(1).strip()
            task_type: Literal["system", "reminder"] = (
                "system" if re.search(r"^Type:\s*system", block, re.MULTILINE) else "reminder"
            )

            schedule_match = re.search(
                r"Schedule:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", block
            )
            if not schedule_match:
                continue
            schedule_str = schedule_match.group(1).strip()

            try:
                if " " in schedule_str:
                    schedule_dt = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
                else:
                    schedule_dt = datetime.strptime(schedule_str, "%Y-%m-%d")
            except ValueError:
                continue

            # Skip tasks past their Until date
            until_match = re.search(r"Until:\s*(\d{4}-\d{2}-\d{2})", block)
            if until_match:
                try:
                    until_dt = datetime.strptime(until_match.group(1), "%Y-%m-%d")
                    if now > until_dt:
                        continue
                except ValueError:
                    pass

            if now >= schedule_dt:
                due.append(DueTask(name=task_name, task_type=task_type, schedule=schedule_str))

        return due

    @staticmethod
    def _compute_task_statuses(content: str, now: datetime) -> str:
        """Parse ## User Tasks section and compute due status in Python.

        Returns a formatted string describing which tasks are DUE NOW and which
        are not yet due, or "" if no tasks with Schedule fields are found.
        """
        # Schedule strings are naive; strip tzinfo for comparison
        now = now.replace(tzinfo=None)
        user_tasks_match = re.search(r"^## User Tasks\s*$", content, re.MULTILINE)
        if not user_tasks_match:
            return ""

        section_start = user_tasks_match.end()
        next_section_match = re.search(r"^## ", content[section_start:], re.MULTILINE)
        if next_section_match:
            section_end = section_start + next_section_match.start()
        else:
            section_end = len(content)
        section = content[section_start:section_end]

        task_blocks = re.split(r"\n(?=###\s)", section)
        lines = []

        for block in task_blocks:
            block = block.strip()
            if not block.startswith("###"):
                continue

            name_match = re.match(r"###\s+(.+)", block)
            if not name_match:
                continue
            task_name = name_match.group(1).strip()

            schedule_match = re.search(
                r"Schedule:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", block
            )
            if not schedule_match:
                continue
            schedule_str = schedule_match.group(1).strip()

            if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", schedule_str):
                try:
                    schedule_dt = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            else:
                try:
                    schedule_dt = datetime.strptime(schedule_str, "%Y-%m-%d")
                except ValueError:
                    continue

            until_match = re.search(r"Until:\s*(\d{4}-\d{2}-\d{2})", block)
            if until_match:
                try:
                    until_dt = datetime.strptime(until_match.group(1), "%Y-%m-%d")
                    if now > until_dt:
                        continue
                except ValueError:
                    pass

            now_str = now.strftime("%Y-%m-%d %H:%M")
            if now >= schedule_dt:
                lines.append(
                    f"  - '{task_name}' IS DUE NOW "
                    f"(scheduled {schedule_str}, now is {now_str})"
                )
            else:
                lines.append(
                    f"  - '{task_name}' is NOT due until {schedule_str}"
                )

        if not lines:
            return ""

        return (
            "Python-computed task due status (authoritative — trust this over your own date math):\n"
            + "\n".join(lines)
        )

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: determine whether any tasks are due.

        When last_run_tracking=True: fully deterministic, no LLM call.
        When last_run_tracking=False: falls back to LLM tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        from nanobot.utils.helpers import current_time_str
        from zoneinfo import ZoneInfo
        try:
            tz = ZoneInfo(self.timezone) if self.timezone else None
        except (KeyError, Exception):
            tz = None
        now = datetime.now(tz=tz) if tz else datetime.now().astimezone()

        if self.last_run_tracking:
            due = self._compute_due_tasks(content, now.replace(tzinfo=None))
            if not due:
                return "skip", ""
            summary = ", ".join(f"{t.name} ({t.task_type})" for t in due)
            logger.debug("Heartbeat: {} due task(s) — {}", len(due), summary)
            return "run", summary

        # LLM fallback when last_run_tracking is disabled
        now_str = current_time_str(self.timezone)
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    f"Current Time: {now_str}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there are tasks DUE NOW "
                    "(scheduled date/time has already passed or is within the next 5 minutes). "
                    "Tasks scheduled for a future date are NOT due — choose 'skip' for those. \n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from nanobot.utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)

                if response:
                    should_notify = await evaluate_response(
                        response, tasks, self.provider, self.model,
                        suppress_errors=self.suppress_errors,
                    )
                    if should_notify and self.on_notify:
                        logger.info("Heartbeat: completed, delivering response")
                        await self.on_notify(response)
                    else:
                        logger.info("Heartbeat: silenced by post-run evaluation")
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
