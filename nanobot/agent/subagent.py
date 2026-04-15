"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.agent.hooks.nanocats_hook import create_subagent_hook
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.nanocats import NanoCatsTaskTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import GlobTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig, WebToolsConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.prompt_templates import render_template


class SubagentManager:
    """Manages background subagent execution."""

    class _SubagentTraceHook(AgentHook):
        """Structured tool/usage logging for subagents."""

        def __init__(self, agent_name: str, task_id: str, label: str):
            super().__init__()
            self._agent_name = agent_name
            self._task_id = task_id
            self._label = label

        async def before_execute_tools(self, context: AgentHookContext) -> None:
            for tc in context.tool_calls:
                args_str = json.dumps(tc.arguments, ensure_ascii=False)
                logger.info(
                    "Tool call [{} {}|{}]: {}({})",
                    self._agent_name,
                    self._task_id,
                    self._label,
                    tc.name,
                    args_str[:200],
                )

        async def after_iteration(self, context: AgentHookContext) -> None:
            u = context.usage or {}
            logger.debug(
                "LLM usage [{} {}|{}]: prompt={} completion={} cached={}",
                self._agent_name,
                self._task_id,
                self._label,
                u.get("prompt_tokens", 0),
                u.get("completion_tokens", 0),
                u.get("cached_tokens", 0),
            )

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
        on_task_start: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_task_complete: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
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
        self._on_task_start = on_task_start
        self._on_task_complete = on_task_complete

    def set_on_task_start(
        self,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        self._on_task_start = callback

    def set_on_task_complete(
        self,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        self._on_task_complete = callback

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        task_meta: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        # Canonical role names for core subagents.
        role_name = str((task_meta or {}).get("subagent_name") or "")
        if role_name in {"Vicks", "Wedge", "Rydia"}:
            display_label = role_name
        else:
            low = display_label.lower()
            if low.startswith("vicks"):
                display_label = "Vicks"
            elif low.startswith("wedge"):
                display_label = "Wedge"
            elif low.startswith("rydia"):
                display_label = "Rydia"

        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        if self._on_task_start:
            try:
                await self._on_task_start(
                    {
                        "task_id": task_id,
                        "label": display_label,
                        "task": task,
                        "origin": origin,
                        "task_meta": task_meta or {},
                    }
                )
            except Exception:
                logger.exception("Subagent [{}] start callback failed", task_id)

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, task_meta or {})
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

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        task_meta: dict[str, Any],
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = (
                self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
            )
            extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
            tools.register(
                ReadFileTool(
                    workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read
                )
            )
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(GlobTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(GrepTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(NanoCatsTaskTool())
            if self.exec_config.enable:
                tools.register(
                    ExecTool(
                        working_dir=str(self.workspace),
                        timeout=self.exec_config.timeout,
                        restrict_to_workspace=self.restrict_to_workspace,
                        sandbox=self.exec_config.sandbox,
                        path_append=self.exec_config.path_append,
                    )
                )
            if self.web_config.enable:
                tools.register(
                    WebSearchTool(config=self.web_config.search, proxy=self.web_config.proxy)
                )
                tools.register(WebFetchTool(proxy=self.web_config.proxy))
            system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            result = await self.runner.run(
                AgentRunSpec(
                    initial_messages=messages,
                    tools=tools,
                    model=self.model,
                    max_iterations=15,
                    max_tool_result_chars=self.max_tool_result_chars,
                    hook=CompositeHook(
                        [
                            create_subagent_hook(task_id, label, self.workspace),
                            self._SubagentTraceHook(label, task_id, label),
                        ]
                    ),
                    max_iterations_message="Task completed but no final response was generated.",
                    error_message=None,
                    fail_on_tool_error=True,
                )
            )
            if result.stop_reason == "tool_error":
                await self._announce_result(
                    task_id,
                    label,
                    task,
                    self._format_partial_progress(result),
                    origin,
                    "error",
                    task_meta,
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
                    task_meta,
                )
                return
            final_result = (
                result.final_content or "Task completed but no final response was generated."
            )

            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok", task_meta)

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error", task_meta)

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        task_meta: dict[str, Any],
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
        logger.debug(
            "Subagent [{}] announced result to {}:{}", task_id, origin["channel"], origin["chat_id"]
        )

        if self._on_task_complete:
            try:
                await self._on_task_complete(
                    {
                        "task_id": task_id,
                        "subagent_runtime_id": f"subagent-{task_id}",
                        "label": label,
                        "status": status,
                        "task": task,
                        "result": result,
                        "origin": origin,
                        "task_meta": task_meta,
                    }
                )
            except Exception:
                logger.exception("Subagent [{}] completion callback failed", task_id)

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
        tasks = [
            self._running_tasks[tid]
            for tid in self._session_tasks.get(session_key, [])
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        ]
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
            1 for tid in tids if tid in self._running_tasks and not self._running_tasks[tid].done()
        )
