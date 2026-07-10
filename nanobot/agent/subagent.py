"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.context import (
    RequestContext,
    ToolContext,
    bind_request_context,
    reset_request_context,
)
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, ToolsConfig
from nanobot.providers.base import LLMProvider
from nanobot.security.workspace_access import (
    WorkspaceScope,
    bind_workspace_scope,
    reset_workspace_scope,
    workspace_sandbox_status,
)
from nanobot.utils.helpers import truncate_text
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

SubagentResultMode = Literal["realtime", "aggregated"]
SubagentResultStatus = Literal["ok", "error", "mixed"]
_AGGREGATED_RESULT_MAX_ITEMS = 20
_AGGREGATED_RESULT_MAX_TASK_CHARS = 500
_AGGREGATED_RESULT_MAX_RESULT_CHARS = 4_000
_AGGREGATED_RESULT_MAX_REPORT_CHARS = 32_000


@dataclass(slots=True)
class SubagentStatus:
    """Real-time status of a running subagent."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    phase: str = "initializing"  # initializing | awaiting_tools | tools_completed | final_response | done | error
    iteration: int = 0
    tool_events: list = field(default_factory=list)   # [{name, status, detail}, ...]
    usage: dict = field(default_factory=dict)          # token usage
    stop_reason: str | None = None
    error: str | None = None


@dataclass(slots=True)
class _SubagentResult:
    """Completed subagent result waiting for announcement."""

    task_id: str
    label: str
    task: str
    result: str
    origin: dict[str, str | None]
    status: SubagentResultStatus
    origin_message_id: str | None = None


class _SubagentHook(AgentHook):
    """Hook for subagent execution — logs tool calls and updates status."""

    def __init__(self, task_id: str, status: SubagentStatus | None = None) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = dict(context.usage)
        if context.error:
            self._status.error = str(context.error)


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        workspace: Path | None = None,
        bus: MessageBus | None = None,
        max_tool_result_chars: int | None = None,
        model: str | None = None,
        tools_config: ToolsConfig | None = None,
        restrict_to_workspace: bool = False,
        disabled_skills: list[str] | None = None,
        max_iterations: int | None = None,
        max_concurrent_subagents: int | None = None,
        result_mode: SubagentResultMode = "realtime",
        fail_on_tool_error: bool | None = None,
        llm_wall_timeout_for_session: Callable[[str | None], float | None] | None = None,
    ):
        if workspace is None:
            raise TypeError("SubagentManager.__init__() missing required argument: 'workspace'")
        if bus is None:
            raise TypeError("SubagentManager.__init__() missing required argument: 'bus'")
        if max_tool_result_chars is None:
            raise TypeError(
                "SubagentManager.__init__() missing required argument: 'max_tool_result_chars'"
            )
        if model is not None and provider is None:
            raise TypeError("SubagentManager model compatibility argument requires provider")
        if result_mode not in ("realtime", "aggregated"):
            raise ValueError("result_mode must be 'realtime' or 'aggregated'")
        defaults = AgentDefaults()
        self._compat_runtime: LLMRuntime | None = None
        if provider is not None:
            warnings.warn(
                "SubagentManager provider/model constructor arguments are deprecated; "
                "pass runtime=... to spawn() instead",
                DeprecationWarning,
                stacklevel=2,
            )
            self._compat_runtime = LLMRuntime.capture(
                provider,
                model or provider.get_default_model(),
                context_window_tokens=defaults.context_window_tokens,
            )
        self.workspace = workspace
        self.bus = bus
        self.result_mode = result_mode
        self.tools_config = tools_config or ToolsConfig()
        self.max_tool_result_chars = max_tool_result_chars
        self.restrict_to_workspace = restrict_to_workspace
        self.disabled_skills = set(disabled_skills or [])
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else defaults.max_tool_iterations
        )
        self.max_concurrent_subagents = (
            max_concurrent_subagents
            if max_concurrent_subagents is not None
            else defaults.max_concurrent_subagents
        )
        self.fail_on_tool_error = (
            fail_on_tool_error
            if fail_on_tool_error is not None
            else defaults.fail_on_tool_error
        )
        self.runner = AgentRunner()
        self._llm_wall_timeout_for_session = llm_wall_timeout_for_session
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        self._pending_aggregated_results: dict[str, list[_SubagentResult]] = {}
        self._pending_aggregated_omitted_counts: dict[str, int] = {}
        self._pending_aggregated_omitted_statuses: dict[str, set[SubagentResultStatus]] = {}
        self._cancelled_aggregated_sessions: set[str] = set()

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        """Update the deprecated runtime source used by legacy ``spawn`` calls."""
        warnings.warn(
            "SubagentManager.set_provider() is deprecated; pass runtime=... to spawn() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        context_window_tokens = (
            self._compat_runtime.context_window_tokens
            if self._compat_runtime is not None
            else AgentDefaults().context_window_tokens
        )
        self._compat_runtime = LLMRuntime.capture(
            provider,
            model,
            context_window_tokens=context_window_tokens,
        )

    def _compat_spawn_runtime(self) -> LLMRuntime:
        runtime = self._compat_runtime
        if runtime is None:
            raise TypeError(
                "SubagentManager.spawn() missing required keyword-only argument: 'runtime'"
            )
        warnings.warn(
            "SubagentManager.spawn() without runtime is deprecated; pass runtime=... explicitly",
            DeprecationWarning,
            stacklevel=3,
        )
        return LLMRuntime.capture(
            runtime.provider,
            runtime.model,
            context_window_tokens=runtime.context_window_tokens,
        )

    def _subagent_tools_config(self) -> ToolsConfig:
        """Build a ToolsConfig scoped for subagent use."""
        return ToolsConfig(
            exec=self.tools_config.exec,
            web=self.tools_config.web,
            file=self.tools_config.file,
            restrict_to_workspace=self.restrict_to_workspace,
        )

    def _build_tools(
        self,
        workspace: Path | None = None,
        tools_config: ToolsConfig | None = None,
    ) -> ToolRegistry:
        """Build an isolated subagent tool registry via ToolLoader."""
        root = self.workspace if workspace is None else workspace
        registry = ToolRegistry()
        cfg = tools_config if tools_config is not None else self._subagent_tools_config()
        ctx = ToolContext(
            config=cfg,
            workspace=str(root.resolve()),
            file_state_store=FileStates(),
            workspace_sandbox=workspace_sandbox_status(
                restrict_to_workspace=cfg.restrict_to_workspace,
                workspace=root,
            ),
        )
        ToolLoader().load(ctx, registry, scope="subagent")
        return registry

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
        *,
        runtime: LLMRuntime | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        if runtime is None:
            runtime = self._compat_spawn_runtime()
        if temperature is not None:
            runtime = runtime.with_generation_overrides(temperature=temperature)
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin: dict[str, str | None] = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
            "session_key": session_key,
        }

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
        )
        self._task_statuses[task_id] = status

        bg_task = asyncio.create_task(
            self._run_subagent(
                task_id,
                task,
                display_label,
                origin,
                status,
                runtime,
                origin_message_id,
                workspace_scope,
            )
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            should_flush = False
            self._running_tasks.pop(task_id, None)
            self._task_statuses.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]
                    was_cancelled = session_key in self._cancelled_aggregated_sessions
                    should_flush = self.result_mode == "aggregated" and not was_cancelled
                    self._cancelled_aggregated_sessions.discard(session_key)
            if should_flush and session_key:
                asyncio.create_task(self._flush_aggregated_results(session_key))

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str | None],
        status: SubagentStatus,
        runtime: LLMRuntime,
        origin_message_id: str | None = None,
        workspace_scope: WorkspaceScope | None = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        async def _on_checkpoint(payload: dict) -> None:
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)

        try:
            root = workspace_scope.project_path if workspace_scope is not None else self.workspace
            cfg = None
            if workspace_scope is not None:
                cfg = self._subagent_tools_config()
                cfg.restrict_to_workspace = workspace_scope.restrict_to_workspace
            tools = self._build_tools(workspace=root, tools_config=cfg)
            system_prompt = self._build_subagent_prompt(workspace=root)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            sess_key = origin.get("session_key")
            llm_timeout = (
                self._llm_wall_timeout_for_session(sess_key)
                if self._llm_wall_timeout_for_session
                else None
            )
            request_token = bind_request_context(RequestContext(
                channel=origin["channel"],
                chat_id=origin["chat_id"],
                message_id=origin_message_id,
                session_key=sess_key,
                runtime=runtime,
            ))
            token = bind_workspace_scope(workspace_scope) if workspace_scope is not None else None
            try:
                result = await self.runner.run(AgentRunSpec(
                    initial_messages=messages,
                    tools=tools,
                    runtime=runtime,
                    max_iterations=self.max_iterations,
                    max_tool_result_chars=self.max_tool_result_chars,
                    hook=_SubagentHook(task_id, status),
                    max_iterations_message="Task completed but no final response was generated.",
                    finalize_on_max_iterations=False,
                    error_message=None,
                    fail_on_tool_error=self.fail_on_tool_error,
                    checkpoint_callback=_on_checkpoint,
                    session_key=sess_key,
                    workspace=root,
                    llm_timeout_s=llm_timeout,
                ))
            finally:
                if token is not None:
                    reset_workspace_scope(token)
                reset_request_context(request_token)
            status.phase = "done"
            status.stop_reason = result.stop_reason

            if result.stop_reason == "tool_error":
                status.tool_events = list(result.tool_events)
                await self._complete_subagent_result(
                    task_id, label, task,
                    self._format_partial_progress(result),
                    origin, "error", origin_message_id,
                )
            elif result.stop_reason == "error":
                await self._complete_subagent_result(
                    task_id, label, task,
                    result.error or "Error: subagent execution failed.",
                    origin, "error", origin_message_id,
                )
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                logger.info("Subagent [{}] completed successfully", task_id)
                await self._complete_subagent_result(
                    task_id, label, task, final_result, origin, "ok", origin_message_id
                )

        except Exception as e:
            status.phase = "error"
            status.error = str(e)
            logger.exception("Subagent [{}] failed", task_id)
            await self._complete_subagent_result(
                task_id, label, task, f"Error: {e}", origin, "error", origin_message_id
            )

    async def _complete_subagent_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str | None],
        status: SubagentResultStatus,
        origin_message_id: str | None = None,
    ) -> None:
        """Announce immediately or buffer until all session subagents finish."""
        session_key = origin.get("session_key")
        if self.result_mode != "aggregated" or not session_key:
            await self._announce_result(
                task_id, label, task, result, origin, status, origin_message_id
            )
            return
        if session_key in self._cancelled_aggregated_sessions:
            self._discard_aggregated_results(session_key)
            return

        pending_results = self._pending_aggregated_results.setdefault(session_key, [])
        if len(pending_results) < _AGGREGATED_RESULT_MAX_ITEMS:
            pending_results.append(_SubagentResult(
                task_id=task_id,
                label=label,
                task=task,
                result=result,
                origin=origin,
                status=status,
                origin_message_id=origin_message_id,
            ))
        else:
            self._pending_aggregated_omitted_counts[session_key] = (
                self._pending_aggregated_omitted_counts.get(session_key, 0) + 1
            )
            self._pending_aggregated_omitted_statuses.setdefault(session_key, set()).add(status)

        active_task_ids = self._session_tasks.get(session_key)
        if not active_task_ids or task_id not in active_task_ids:
            await self._flush_aggregated_results(session_key)

    def _discard_aggregated_results(self, session_key: str) -> None:
        """Drop buffered aggregate output for a session that is being cancelled."""
        self._pending_aggregated_results.pop(session_key, None)
        self._pending_aggregated_omitted_counts.pop(session_key, None)
        self._pending_aggregated_omitted_statuses.pop(session_key, None)

    async def _flush_aggregated_results(self, session_key: str) -> None:
        """Publish one combined result for all completed subagents in a session."""
        results = self._pending_aggregated_results.pop(session_key, [])
        omitted_count = self._pending_aggregated_omitted_counts.pop(session_key, 0)
        omitted_statuses = self._pending_aggregated_omitted_statuses.pop(session_key, set())
        if not results and not omitted_count:
            return
        if len(results) == 1 and not omitted_count:
            result = results[0]
            await self._announce_result(
                result.task_id,
                result.label,
                result.task,
                result.result,
                result.origin,
                result.status,
                result.origin_message_id,
            )
            return

        total_count = len(results) + omitted_count
        task_ids = [result.task_id for result in results]
        origin_message_ids = list(dict.fromkeys(
            origin_id for origin_id in (result.origin_message_id for result in results) if origin_id
        ))
        primary_origin_message_id = origin_message_ids[0] if origin_message_ids else None
        extra_metadata: dict[str, Any] = {
            "subagent_result_mode": "aggregated",
            "subagent_task_ids": task_ids,
            "subagent_result_count": total_count,
        }
        if omitted_count:
            extra_metadata["subagent_omitted_result_count"] = omitted_count
        if origin_message_ids:
            extra_metadata["origin_message_ids"] = origin_message_ids

        await self._announce_result(
            "aggregate:" + ",".join(task_ids),
            f"{total_count} background tasks",
            f"Aggregated report for {total_count} background tasks.",
            self._format_aggregated_results(results, omitted_count=omitted_count),
            results[0].origin,
            self._aggregate_status(results, omitted_statuses),
            primary_origin_message_id,
            extra_metadata=extra_metadata,
        )

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str | None],
        status: SubagentResultStatus,
        origin_message_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = {
            "ok": "completed successfully",
            "error": "failed",
            "mixed": "completed with mixed results",
        }[status]

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
        )

        # Inject as system message to trigger main agent.
        # Use session_key_override to align with the main agent's effective
        # session key (which accounts for unified sessions) so the result is
        # routed to the correct pending queue (mid-turn injection) instead of
        # being dispatched as a competing independent task.
        override = origin.get("session_key") or f"{origin['channel']}:{origin['chat_id']}"
        metadata: dict[str, Any] = {
            "injected_event": "subagent_result",
            "subagent_task_id": task_id,
        }
        if origin_message_id:
            metadata["origin_message_id"] = origin_message_id
        if extra_metadata:
            metadata.update(extra_metadata)
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            session_key_override=override,
            metadata=metadata,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    @staticmethod
    def _aggregate_status(
        results: list[_SubagentResult],
        omitted_statuses: set[SubagentResultStatus] | None = None,
    ) -> SubagentResultStatus:
        statuses = {result.status for result in results}
        statuses.update(omitted_statuses or set())
        if not statuses or statuses == {"ok"}:
            return "ok"
        if statuses == {"error"}:
            return "error"
        return "mixed"

    def _format_aggregated_results(
        self,
        results: list[_SubagentResult],
        *,
        omitted_count: int = 0,
    ) -> str:
        lines: list[str] = []
        visible_results = results[:_AGGREGATED_RESULT_MAX_ITEMS]
        for idx, result in enumerate(visible_results, start=1):
            status_text = "completed successfully" if result.status == "ok" else "failed"
            lines.append(f"### {idx}. {result.label} ({status_text})")
            lines.append("")
            lines.append(f"Task: {truncate_text(result.task, _AGGREGATED_RESULT_MAX_TASK_CHARS)}")
            lines.append("")
            lines.append("Result:")
            lines.append(truncate_text(result.result, _AGGREGATED_RESULT_MAX_RESULT_CHARS))
            if idx != len(visible_results):
                lines.append("")
        omitted = omitted_count + len(results) - len(visible_results)
        if omitted > 0:
            if lines:
                lines.append("")
            lines.append(
                f"... {omitted} additional subagent result"
                f"{'s' if omitted != 1 else ''} omitted from this aggregated report."
            )
        report = "\n".join(lines)
        max_report_chars = min(
            self.max_tool_result_chars
            if self.max_tool_result_chars > 0
            else _AGGREGATED_RESULT_MAX_REPORT_CHARS,
            _AGGREGATED_RESULT_MAX_REPORT_CHARS,
        )
        return truncate_text(report, max_report_chars)

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

    def _build_subagent_prompt(self, workspace: Path | None = None) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        root = workspace or self.workspace
        skills_summary = SkillsLoader(
            root,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary()
        return render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(root),
            skills_summary=skills_summary or "",
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        if self.result_mode == "aggregated" and (
            tasks or session_key in self._pending_aggregated_results
        ):
            self._discard_aggregated_results(session_key)
            self._cancelled_aggregated_sessions.add(session_key)
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
