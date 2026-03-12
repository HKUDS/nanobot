"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

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


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

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
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.last_run_tracking = last_run_tracking
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    @staticmethod
    def _compute_task_statuses(content: str, now: datetime) -> str:
        """Parse ## User Tasks section and compute due status in Python.

        Returns a formatted string describing which tasks are DUE NOW and which
        are not yet due, or "" if no tasks with Schedule fields are found.
        """
        # Find the ## User Tasks section
        user_tasks_match = re.search(r"^## User Tasks\s*$", content, re.MULTILINE)
        if not user_tasks_match:
            return ""

        # Find the end of the section (next ## heading or end of string)
        section_start = user_tasks_match.end()
        next_section_match = re.search(r"^## ", content[section_start:], re.MULTILINE)
        if next_section_match:
            section_end = section_start + next_section_match.start()
        else:
            section_end = len(content)
        section = content[section_start:section_end]

        # Parse each ### TaskName block
        task_blocks = re.split(r"\n(?=###\s)", section)
        lines = []

        for block in task_blocks:
            block = block.strip()
            if not block.startswith("###"):
                continue

            # Extract task name
            name_match = re.match(r"###\s+(.+)", block)
            if not name_match:
                continue
            task_name = name_match.group(1).strip()

            # Extract Schedule field — support YYYY-MM-DD HH:MM or YYYY-MM-DD
            schedule_match = re.search(
                r"Schedule:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", block
            )
            if not schedule_match:
                continue
            schedule_str = schedule_match.group(1).strip()

            # Parse schedule datetime
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

            # Extract Until field and skip expired tasks
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
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")
        last_run_instruction = ""
        if self.last_run_tracking:
            computed = self._compute_task_statuses(content, now)
            if computed:
                last_run_instruction = computed + "\n"
            else:
                today_str = now.strftime("%Y-%m-%d")
                last_run_instruction = (
                    f"Evaluate each task independently: if a task has a 'Last-run' field dated {today_str}, "
                    "that specific task already ran today — skip it. Other tasks are unaffected. "
                )
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    f"Current date/time: {now_str}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there are tasks DUE NOW "
                    "(scheduled date/time has already passed or is within the next 5 minutes). "
                    "Tasks scheduled for a future date are NOT due — choose 'skip' for those. "
                    f"{last_run_instruction}\n\n"
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
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
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
