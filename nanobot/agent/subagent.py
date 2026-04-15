"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.utils.prompt_templates import render_template
from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import GlobTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig, WebToolsConfig
from nanobot.providers.base import LLMProvider


@dataclass
class _TaskInfo:
    """Tracks metadata for a spawned subagent task."""
    task_id: str
    label: str
    task: str
    started_at: float
    status: str = "running"  # running | done | error | incomplete
    final_content: str | None = None
    elapsed: float = 0.0
    missing_files: list[str] = field(default_factory=list)


class _SubagentHook(AgentHook):
    """Logging-only hook for subagent execution."""

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self._task_id = task_id

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        max_tool_result_chars: int,
        model: str | None = None,
        web_config: "WebToolsConfig | None" = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        disabled_skills: list[str] | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig

        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.web_config = web_config or WebToolsConfig()
        self.max_tool_result_chars = max_tool_result_chars
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.disabled_skills = set(disabled_skills or [])
        self.runner = AgentRunner(provider)
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        self._task_info: dict[str, _TaskInfo] = {}
        self._completed_tasks: dict[str, _TaskInfo] = {}  # keeps last 10

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        timeout_seconds: int | None = None,
        max_iterations: int | None = None,
        expected_files: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        self._task_info[task_id] = _TaskInfo(
            task_id=task_id,
            label=display_label,
            task=task,
            started_at=time.time(),
        )

        bg_task = asyncio.create_task(
            self._run_subagent(
                task_id, task, display_label, origin,
                timeout_seconds=timeout_seconds,
                max_iterations=max_iterations,
                expected_files=expected_files,
            )
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]
            # Move to completed
            info = self._task_info.pop(task_id, None)
            if info:
                info.elapsed = round(time.time() - info.started_at, 1)
                self._completed_tasks[task_id] = info
                # Keep only last 10
                while len(self._completed_tasks) > 10:
                    oldest = next(iter(self._completed_tasks))
                    del self._completed_tasks[oldest]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        timeout_seconds: int | None = None,
        max_iterations: int | None = None,
        expected_files: str | None = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        # Optional timeout wrapper
        run_coro = self._execute_subagent(task_id, task, label, origin, max_iterations)
        if timeout_seconds is not None:
            try:
                await asyncio.wait_for(run_coro, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                info = self._task_info.get(task_id)
                if info:
                    info.status = "error"
                logger.warning("Subagent [{}] timed out after {}s", task_id, timeout_seconds)
                await self._announce_result(
                    task_id, label, task,
                    f"Subagent timed out after {timeout_seconds} seconds.",
                    origin, "error",
                )
        else:
            await run_coro

        # Verify expected files
        if expected_files:
            self._check_expected_files(task_id, expected_files)

    async def _execute_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        max_iterations: int | None = None,
    ) -> None:
        """Core subagent execution logic."""

        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
            extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(GlobTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(GrepTool(workspace=self.workspace, allowed_dir=allowed_dir))
            if self.exec_config.enable:
                tools.register(ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                    sandbox=self.exec_config.sandbox,
                    path_append=self.exec_config.path_append,
                ))
            if self.web_config.enable:
                tools.register(WebSearchTool(config=self.web_config.search, proxy=self.web_config.proxy))
                tools.register(WebFetchTool(proxy=self.web_config.proxy))
            system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=self.model,
                max_iterations=max_iterations or 15,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(task_id),
                max_iterations_message="Task completed but no final response was generated.",
                error_message=None,
                fail_on_tool_error=True,
            ))
            if result.stop_reason == "tool_error":
                await self._announce_result(
                    task_id,
                    label,
                    task,
                    self._format_partial_progress(result),
                    origin,
                    "error",
                )
                return
            if result.stop_reason == "error":
                await self._announce_result(
                    task_id,
                    label,
                    task,
                    result.error or "Error: subagent execution failed.",
                    origin,
                    "error",
                )
                return
            final_result = result.final_content or "Task completed but no final response was generated."

            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
            return

        except Exception as e:
            info = self._task_info.get(task_id)
            if info:
                info.status = "error"
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    def _check_expected_files(self, task_id: str, expected_files: str) -> None:
        """Verify expected files exist; mark task incomplete if any missing."""
        paths = [p.strip() for p in expected_files.split(",") if p.strip()]
        missing = [p for p in paths if not Path(p).exists()]
        info = self._completed_tasks.get(task_id)
        if info and missing:
            info.status = "incomplete"
            info.missing_files = missing
            logger.warning(
                "Subagent [{}] missing expected files: {}", task_id, ", ".join(missing)
            )

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
        )

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    @staticmethod
    def _format_partial_progress(result) -> str:
        completed = [e for e in result.tool_events if e["status"] == "ok"]
        failure = next((e for e in reversed(result.tool_events) if e["status"] == "error"), None)
        lines: list[str] = []
        if completed:
            lines.append("Completed steps:")
            for event in completed[-3:]:
                lines.append(f"- {event['name']}: {event['detail']}")
        if failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {failure['name']}: {failure['detail']}")
        if result.error and not failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {result.error}")
        return "\n".join(lines) or (result.error or "Error: subagent execution failed.")

    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        skills_summary = SkillsLoader(
            self.workspace,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary()
        return render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(self.workspace),
            skills_summary=skills_summary or "",
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def get_running_count_by_session(self, session_key: str) -> int:
        """Return the number of currently running subagents for a session."""
        tids = self._session_tasks.get(session_key, set())
        return sum(
            1 for tid in tids
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        )

    def get_task_status(self, task_id: str | None = None) -> str:
        """Return status of running or recently completed subagents."""
        if task_id:
            # Check running first, then completed
            info = self._task_info.get(task_id) or self._completed_tasks.get(task_id)
            if info is None:
                return f"Task {task_id} not found."
            status_line = f"Task [{info.label}] (id: {info.task_id}) — {info.status}"
            if info.elapsed:
                status_line += f" — {info.elapsed}s"
            if info.missing_files:
                status_line += f"\nMissing files: {', '.join(info.missing_files)}"
            return status_line

        # List all running + recently completed
        lines: list[str] = []
        for tid, info in self._task_info.items():
            elapsed = round(time.time() - info.started_at, 1)
            lines.append(f"[{info.status}] {info.label} (id: {tid}) — {elapsed}s")
        for tid, info in self._completed_tasks.items():
            lines.append(f"[{info.status}] {info.label} (id: {tid}) — {info.elapsed}s")
            if info.missing_files:
                lines.append(f"  Missing: {', '.join(info.missing_files)}")
        if not lines:
            return "No running or recently completed subagents."
        return "\n".join(lines)

    async def cancel_by_task_id(self, task_id: str) -> str:
        """Cancel a running subagent by task ID. Returns status message."""
        if task_id not in self._running_tasks:
            return f"Task {task_id} is not currently running."
        task = self._running_tasks[task_id]
        if task.done():
            return f"Task {task_id} has already finished."
        task.cancel()
        info = self._task_info.get(task_id)
        if info:
            info.status = "error"
        try:
            await task
        except asyncio.CancelledError:
            pass
        return f"Task {task_id} cancelled."
