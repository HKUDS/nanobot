"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
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
        timezone: str | None = None,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.timezone = timezone
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    @staticmethod
    def _has_active_tasks(content: str) -> bool:
        """Return True when HEARTBEAT.md contains actionable task text."""
        active_lines = HeartbeatService._active_task_section_lines(content)
        if active_lines is None:
            active_lines = content.splitlines()

        in_html_comment = False
        for line in active_lines:
            line, in_html_comment = HeartbeatService._strip_html_comment(line, in_html_comment)
            normalized = line.strip()
            if not normalized:
                continue
            if HeartbeatService._is_heartbeat_template_line(normalized):
                continue
            return True
        return False

    @staticmethod
    def _active_task_section_lines(content: str) -> list[str] | None:
        lines = content.splitlines()
        section_start: int | None = None
        section_level: int | None = None

        for index, line in enumerate(lines):
            stripped = line.lstrip()
            level = len(stripped) - len(stripped.lstrip("#"))
            if level == 0 or level > 6 or not stripped[level:].startswith(" "):
                continue
            title = stripped[level:].strip().casefold()
            if title == "active tasks":
                section_start = index + 1
                section_level = level
                break

        if section_start is None or section_level is None:
            return None

        section_end = len(lines)
        for index in range(section_start, len(lines)):
            stripped = lines[index].lstrip()
            level = len(stripped) - len(stripped.lstrip("#"))
            if 0 < level <= section_level and stripped[level:].startswith(" "):
                section_end = index
                break

        return lines[section_start:section_end]

    @staticmethod
    def _strip_html_comment(line: str, in_comment: bool) -> tuple[str, bool]:
        remaining = line
        output = ""

        while remaining:
            if in_comment:
                end = remaining.find("-->")
                if end == -1:
                    return output, True
                remaining = remaining[end + 3:]
                in_comment = False
                continue

            start = remaining.find("<!--")
            if start == -1:
                output += remaining
                break
            output += remaining[:start]
            remaining = remaining[start + 4:]
            end = remaining.find("-->")
            if end == -1:
                return output, True
            remaining = remaining[end + 3:]

        return output, in_comment

    @staticmethod
    def _is_heartbeat_template_line(line: str) -> bool:
        lower = line.casefold()
        if line.startswith("#"):
            return True
        if lower in {"---", "***", "___"}:
            return True
        return False

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        from nanobot.utils.helpers import current_time_str

        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    f"Current Time: {current_time_str(self.timezone)}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.should_execute_tools:
            if response.has_tool_calls:
                logger.warning(
                    "Ignoring heartbeat tool calls under finish_reason='{}'",
                    response.finish_reason,
                )
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

    @staticmethod
    def _is_deliverable(response: str) -> bool:
        """Check if a heartbeat response is suitable for user delivery.

        Filters out two classes of bad output before the evaluator runs:

        1. **Finalization fallback** — the runner hit empty-response retries
           and produced a canned error message.  For heartbeat, empty output
           is a valid "nothing to report" outcome, not a failure.
        2. **Leaked reasoning** — the model reflected internal file names,
           decision logic, or meta-commentary instead of a user-facing report.
        """
        text = response.lower()

        # Runner finalization fallback
        if "couldn't produce a final answer" in text:
            return False

        # Leaked internal reasoning patterns
        leaked_patterns = [
            "heartbeat.md",
            "awareness.md",
            "judgment call:",
            "decision logic",
            "valid options are",
            "my instructions",
            "i am supposed to",
            "strict heartbeat interpretation",
        ]
        if any(pattern in text for pattern in leaked_patterns):
            return False

        return True

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from nanobot.utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        if not self._has_active_tasks(content):
            logger.debug("Heartbeat: no active tasks, skipping LLM call")
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

                if not response:
                    logger.info("Heartbeat: no response from execution")
                    return

                if not self._is_deliverable(response):
                    logger.info(
                        "Heartbeat: suppressed non-deliverable response ({})",
                        response[:80],
                    )
                    return

                should_notify = await evaluate_response(
                    response, tasks, self.provider, self.model,
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
        if not self._has_active_tasks(content):
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
