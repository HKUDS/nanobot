"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Literal

from loguru import logger
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_SCHED_PAT = re.compile(r"Schedule:\s*(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)")
_RECUR_PAT = re.compile(r"Recur:\s*every\s+(\d+)\s+(minute|hour|day|week)s?", re.IGNORECASE)
_UNTIL_PAT = re.compile(r"Until:\s*(\d{4}-\d{2}-\d{2})")
_LASTRUN_PAT = re.compile(r"Last-run:[^\n]*")

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
    model: str | None = None  # Optional per-task model override
    pre_check: str | None = None  # Optional command to run before LLM dispatch


MODEL_PRESETS: dict[str, str] = {
    "flash25": "gemini/gemini-2.5-flash",
    "flash": "gemini/gemini-3-flash-preview",
    "pro": "gemini/gemini-3.1-pro-preview",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


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
        on_execute: Callable[[str, str | None], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
        last_run_tracking: bool = False,
        timezone: str | None = None,
        suppress_errors: bool = False,
        pre_check_registry: dict[str, str] | None = None,
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
        self.pre_check_registry = pre_check_registry or {}
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _now(self) -> datetime:
        """Return current time in the configured timezone."""
        try:
            tz = ZoneInfo(self.timezone) if self.timezone else None
        except (KeyError, Exception):
            tz = None
        return datetime.now(tz=tz) if tz else datetime.now().astimezone()

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

            model_match = re.search(r"^Model:\s*(.+)", block, re.MULTILINE)
            model = None
            if model_match:
                raw = model_match.group(1).strip()
                model = MODEL_PRESETS.get(raw, raw)  # resolve preset or use as-is

            pre_check_match = re.search(r"^Pre-check:\s*(\S+)", block, re.MULTILINE)
            pre_check = pre_check_match.group(1).strip() if pre_check_match else None

            if now >= schedule_dt:
                due.append(DueTask(
                    name=task_name, task_type=task_type, schedule=schedule_str,
                    model=model, pre_check=pre_check,
                ))

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

    async def _decide(self, content: str) -> tuple[str, str, list[DueTask]]:
        """Phase 1: determine whether any tasks are due.

        When last_run_tracking=True: fully deterministic, no LLM call.
        When last_run_tracking=False: falls back to LLM tool call.

        Returns (action, tasks_str, due_tasks) where action is 'skip' or 'run'.
        due_tasks is populated only when last_run_tracking=True.
        """
        from nanobot.utils.helpers import current_time_str
        now = self._now()

        if self.last_run_tracking:
            due = self._compute_due_tasks(content, now.replace(tzinfo=None))
            if not due:
                return "skip", "", []
            summary = ", ".join(f"{t.name} ({t.task_type})" for t in due)
            logger.debug("Heartbeat: {} due task(s) — {}", len(due), summary)
            return "run", summary, due

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
            return "skip", "", []

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", ""), []

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

    @staticmethod
    async def _run_pre_check(command: str) -> bool:
        """Run a pre-check command. Returns True if the task has work to do.

        A task is skipped (returns False) when the command exits successfully
        and its output is empty, an empty JSON array '[]', or starts with 'SKIP'.
        Non-zero exit codes are treated as errors → proceed with LLM to be safe.
        """
        proc = None
        try:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                logger.warning("Pre-check exited {} for '{}' — proceeding with LLM",
                               proc.returncode, command)
                return True
            output = stdout.decode().strip() if stdout else ""
            if not output or output == "[]" or output.upper().startswith("SKIP"):
                return False
            return True
        except asyncio.TimeoutError:
            logger.warning("Pre-check timed out for '{}' — proceeding with LLM", command)
            if proc:
                proc.kill()
                await proc.communicate()
            return True
        except Exception as e:
            logger.warning("Pre-check failed for '{}': {} — proceeding with LLM", command, e)
            return True  # On error, proceed with LLM to be safe

    async def _filter_by_pre_checks(self, tasks: list[DueTask]) -> list[DueTask]:
        """Run pre-check commands and filter out tasks with no work to do.

        The task's pre_check field is a registry key, resolved to an actual
        command via self.pre_check_registry. Unknown keys are logged and skipped
        (task proceeds to LLM).
        """
        result = []
        for task in tasks:
            if not task.pre_check:
                result.append(task)
                continue
            command = self.pre_check_registry.get(task.pre_check)
            if not command:
                logger.warning("Heartbeat: unknown pre-check key '{}' for '{}' — proceeding with LLM",
                               task.pre_check, task.name)
                result.append(task)
                continue
            has_work = await self._run_pre_check(command)
            if has_work:
                result.append(task)
            else:
                logger.info("Heartbeat: pre-check skipped '{}' (no work)", task.name)
        return result

    def _advance_schedules(self, tasks: list[DueTask]) -> None:
        """Deterministically advance Schedule for executed recurring tasks.

        After a task executes, advance its Schedule past now by its Recur
        interval and write Last-run.  This prevents the task from being
        considered due again on the next heartbeat tick, regardless of
        whether the LLM also calls tasks_update.py --tick.

        Re-reads HEARTBEAT.md fresh to avoid overwriting changes made
        during task execution (which can take 10-30s).
        """
        content = self._read_heartbeat_file()
        if not content:
            return

        now_naive = self._now().replace(tzinfo=None)
        now_str = now_naive.strftime("%Y-%m-%d %H:%M")

        changed = False
        for task in tasks:
            if task.task_type == "announcement" or not task.schedule:
                continue

            escaped = re.escape(task.name)
            block_pat = re.compile(
                rf"(###\s+{escaped}\s*\n)(.*?)(?=\n###\s|\n##\s|\Z)",
                re.DOTALL,
            )
            m = block_pat.search(content)
            if not m:
                logger.warning("Heartbeat: could not find block for '{}' to advance schedule", task.name)
                continue

            block = m.group(0)

            recur_m = _RECUR_PAT.search(block)
            if not recur_m:
                continue

            recur_n = int(recur_m.group(1)) or 1  # treat 0 as 1 to prevent infinite loops
            recur_unit = recur_m.group(2).lower()

            sched_m = _SCHED_PAT.search(block)
            if not sched_m:
                continue
            schedule_str = sched_m.group(1).strip()

            try:
                if " " in schedule_str:
                    current_dt = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
                    has_time = True
                else:
                    current_dt = datetime.strptime(schedule_str, "%Y-%m-%d")
                    has_time = False
            except ValueError:
                continue

            # If the LLM already called --tick during execution, the schedule
            # will already be in the future — skip to avoid double-advancing.
            if current_dt > now_naive:
                logger.info("Heartbeat: '{}' schedule already advanced, skipping", task.name)
                continue

            if recur_unit == "minute":
                delta = timedelta(minutes=recur_n)
            elif recur_unit == "hour":
                delta = timedelta(hours=recur_n)
            elif recur_unit == "week":
                delta = timedelta(weeks=recur_n)
            else:
                delta = timedelta(days=recur_n)

            next_dt = current_dt + delta
            if next_dt <= now_naive:
                intervals = (now_naive - next_dt) // delta + 1
                next_dt += delta * intervals

            if recur_unit in ("minute", "hour") or has_time:
                next_str = next_dt.strftime("%Y-%m-%d %H:%M")
            else:
                next_str = next_dt.strftime("%Y-%m-%d")

            # Note: Until date enforcement is handled by _compute_due_tasks,
            # not here. Always advance the schedule to prevent infinite loops
            # when now < Until < next_dt.

            updated_block = re.sub(
                r"(Schedule:\s*)" + re.escape(schedule_str),
                rf"\g<1>{next_str}",
                block,
                count=1,
            )
            if _LASTRUN_PAT.search(updated_block):
                updated_block = _LASTRUN_PAT.sub(f"Last-run: {now_str}", updated_block, count=1)
            else:
                updated_block = re.sub(
                    r"(Schedule:[^\n]+)(\n|$)",
                    rf"\1\nLast-run: {now_str}\2",
                    updated_block,
                    count=1,
                )

            content = content[:m.start()] + updated_block + content[m.end():]
            changed = True
            logger.info("Heartbeat: advanced '{}' schedule to {}", task.name, next_str)

        if changed:
            self.heartbeat_file.write_text(content, encoding="utf-8")

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from nanobot.utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks_str, due_tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            # Run pre-checks to filter out tasks with no work
            # Only applies when last_run_tracking=True (structured due_tasks).
            # LLM fallback path (due_tasks empty) reads raw HEARTBEAT.md and
            # has no awareness of pre-check results.
            if self.last_run_tracking and due_tasks:
                due_tasks = await self._filter_by_pre_checks(due_tasks)
                if not due_tasks:
                    logger.info("Heartbeat: all tasks skipped by pre-checks")
                    return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                # If no structured tasks (LLM fallback), run as before
                if not due_tasks:
                    response = await self.on_execute(tasks_str, None)
                    if response:
                        should_notify = await evaluate_response(
                            response, tasks_str, self.provider, self.model,
                            suppress_errors=self.suppress_errors,
                        )
                        if should_notify and self.on_notify:
                            logger.info("Heartbeat: completed, delivering response")
                            await self.on_notify(response)
                        else:
                            logger.info("Heartbeat: silenced by post-run evaluation")
                else:
                    # Group tasks by model override
                    groups: dict[str | None, list[DueTask]] = {}
                    for t in due_tasks:
                        groups.setdefault(t.model, []).append(t)

                    for model_override, group_tasks in groups.items():
                        summary = ", ".join(f"{t.name} ({t.task_type})" for t in group_tasks)
                        try:
                            response = await self.on_execute(summary, model_override)
                            if response:
                                should_notify = await evaluate_response(
                                    response, summary, self.provider, self.model,
                                    suppress_errors=self.suppress_errors,
                                )
                                if should_notify and self.on_notify:
                                    logger.info("Heartbeat: completed, delivering response")
                                    await self.on_notify(response)
                                else:
                                    logger.info("Heartbeat: silenced by post-run evaluation")
                        except Exception:
                            logger.exception("Heartbeat: task failed for {}", summary)
                        finally:
                            # Always advance schedule — even on failure — to prevent
                            # retry spam on persistent errors (e.g. API outage).
                            # The task will run again at its next scheduled time.
                            if self.last_run_tracking:
                                self._advance_schedules(group_tasks)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks_str, due_tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None

        # If structured tasks available, group by model and run each group
        if due_tasks:
            groups: dict[str | None, list[DueTask]] = {}
            for t in due_tasks:
                groups.setdefault(t.model, []).append(t)
            results: list[str] = []
            for model_override, group_tasks in groups.items():
                summary = ", ".join(f"{t.name} ({t.task_type})" for t in group_tasks)
                result = await self.on_execute(summary, model_override)
                if result:
                    results.append(result)
            return "\n".join(results) if results else None

        return await self.on_execute(tasks_str, None)
