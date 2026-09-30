"""Subagent manager for background task execution."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
import warnings
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.context import (
    RequestContext,
    ToolContext,
    bind_request_context,
    reset_request_context,
)
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, ToolsConfig
from nanobot.llm_usage.context import LLMUsageSource, current_llm_usage_source
from nanobot.providers.base import LLMProvider, LLMUsage, ToolCallRequest
from nanobot.security.workspace_access import (
    WorkspaceScope,
    bind_workspace_scope,
    reset_workspace_scope,
    workspace_sandbox_status,
)
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class _SubagentOrigin(TypedDict):
    channel: str
    chat_id: str
    session_key: str | None
    llm_usage_source: NotRequired[LLMUsageSource]


@dataclass(slots=True)
class SubagentStatus:
    """Active or retained terminal state of one private task."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    finished_at: float | None = None
    # Runner checkpoints refine phase without changing the control lifecycle state.
    phase: str = "queued"
    owner: str = ""
    state: str = "queued"  # queued | running | stopping | done | error | cancelled
    inbox: list[tuple[str, str]] = field(default_factory=list)
    receipts: dict[str, str] = field(default_factory=dict)
    result: str | None = None
    suppress_notice: bool = False
    begun: bool = False
    exec_manager: ExecSessionManager = field(default_factory=ExecSessionManager)
    cleanup_task: asyncio.Task[int] | None = None
    iteration: int = 0
    tool_events: list[dict[str, str]] = field(default_factory=list)
    usage: LLMUsage | None = None
    stop_reason: str | None = None
    error: str | None = None

    def raise_if_stopping(self) -> None:
        """Check mutable cancellation state after a task suspension."""
        if self.state == "stopping":
            raise asyncio.CancelledError


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

    async def before_execute_tool(
        self, context: AgentHookContext, tool_call: ToolCallRequest,
        tool: Tool | None, params: dict[str, Any],
    ) -> None:
        if self._status is not None:
            self._status.raise_if_stopping()

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = context.usage
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
        *,
        consolidator: Consolidator,
    ):
        if cast(object, consolidator) is None:
            raise TypeError("SubagentManager requires a consolidator")
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
        self.consolidator = consolidator
        self._run_slots = asyncio.Semaphore(self.max_concurrent_subagents)
        self.runner = AgentRunner()
        self._exec_session_manager = ExecSessionManager()
        self._running_tasks: dict[str, asyncio.Task[str]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._terminal_tasks: deque[str] = deque()
        self._resource_owners: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        self._closed = False
        self._close_task: asyncio.Task[int] | None = None

    MAX_ACTIVE = 128
    MAX_TERMINAL = 128
    MAX_INBOX = 16
    MAX_MESSAGES = 128
    MAX_MESSAGE_BYTES = 8192

    CANCEL_WAIT_SECONDS = 5.0

    def _start_cleanup(self, status: SubagentStatus) -> asyncio.Task[int]:
        if status.cleanup_task is None:
            status.cleanup_task = asyncio.create_task(status.exec_manager.close_all())
            status.cleanup_task.add_done_callback(partial(self._cleanup_done, status))
        return status.cleanup_task

    def _cleanup_done(self, status: SubagentStatus, task: asyncio.Task[int]) -> None:
        if not task.cancelled() and task.exception() is None:
            self._resource_owners.pop(status.task_id, None)

    def _at_capacity(self) -> bool:
        # Failed cleanup keeps ownership even after its terminal status is evicted.
        return len(self._running_tasks.keys() | self._resource_owners.keys()) >= self.MAX_ACTIVE

    def _prune_terminal(self) -> None:
        while len(self._terminal_tasks) > self.MAX_TERMINAL:
            tid = self._terminal_tasks.popleft()
            status = self._task_statuses.pop(tid, None)
            if status is None:
                continue
            ids = self._session_tasks.get(status.owner)
            if ids is not None:
                ids.discard(tid)
                if not ids:
                    del self._session_tasks[status.owner]

    def _finish(self, status: SubagentStatus, state: str, result: str) -> None:
        if status.state in {"done", "error", "cancelled"}:
            return
        status.state = status.phase = state
        status.finished_at = time.monotonic()
        status.result = result[:self.max_tool_result_chars]
        status.task_description = status.task_description[:self.max_tool_result_chars]
        status.label = status.label[:256]
        status.tool_events = []
        if status.error:
            status.error = status.error[:self.max_tool_result_chars]
        for message_id, _ in status.inbox:
            status.receipts[message_id] = "undelivered"
        status.inbox.clear()
        self._terminal_tasks.append(status.task_id)
        self._prune_terminal()

    async def _drain_inbox(self, status: SubagentStatus) -> list[dict[str, str]]:
        if status.state != "running":
            raise asyncio.CancelledError
        snapshot, status.inbox = status.inbox, []
        for message_id, _ in snapshot:
            status.receipts[message_id] = "delivered"
        return [{"role": "user", "content": content} for _, content in snapshot]

    async def control(self, task_id: str, owner: str | None, action: str,
                      message: str | None = None) -> str:
        """Control a task only after checking its parent session owner."""
        status = self._task_statuses.get(task_id)
        if not owner or status is None or status.owner != owner:
            return ToolResult.error("Error: task unavailable")
        if action == "send":
            if status.state not in {"queued", "running"}:
                return ToolResult.error("Error: task is not accepting messages")
            if not message or not message.strip() or len(message.encode("utf-8")) > self.MAX_MESSAGE_BYTES:
                return ToolResult.error("Error: message must contain text and be at most 8192 UTF-8 bytes")
            if len(status.inbox) >= self.MAX_INBOX or len(status.receipts) >= self.MAX_MESSAGES:
                return ToolResult.error("Error: task message capacity reached")
            message_id = str(uuid.uuid4())
            status.inbox.append((message_id, message))
            status.receipts[message_id] = "accepted"
            return json.dumps({"task_id": task_id, "message_id": message_id,
                               "receipt": "accepted", "delivered": False})
        if action == "cancel":
            await self._cancel_task(task_id)
        else:
            return ToolResult.error("Error: unknown subagent action")
        return json.dumps({"task_id": task_id, "state": status.state,
                           "receipts": status.receipts, "result": status.result,
                           "error": status.error}, ensure_ascii=False)

    async def _cancel_task(self, task_id: str, *, suppress_notice: bool = False) -> None:
        status = self._task_statuses.get(task_id)
        if status is None:
            return
        status.suppress_notice |= suppress_notice
        task = self._running_tasks.get(task_id)
        if status.state in {"queued", "running"}:
            status.state = status.phase = "stopping"
            if task is not None and status.begun and not task.done():
                task.cancel()
        if status.state == "stopping":
            self._start_cleanup(status)
        if task is not None:
            # wait_for waits for cancellation acknowledgement and can hang here.
            # Keep resistant work tracked, with its slot held, until it really exits.
            await asyncio.wait({task}, timeout=self.CANCEL_WAIT_SECONDS)

    def runtime_statuses(self) -> Mapping[str, SubagentStatus]:
        """Return the observable statuses of all active tasks."""
        return self._task_statuses

    def statuses_for_session(self, session_key: str | None) -> Mapping[str, SubagentStatus]:
        """Return only tasks owned by the given session, never a global fallback."""
        if not session_key:
            return {}
        task_ids = self._session_tasks.get(session_key, set())
        return {
            task_id: status
            for task_id, status in self._task_statuses.items()
            if task_id in task_ids
        }

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
        exec_manager: ExecSessionManager | None = None,
    ) -> ToolRegistry:
        """Build an isolated subagent tool registry via ToolLoader."""
        root = self.workspace if workspace is None else workspace
        registry = ToolRegistry()
        cfg = tools_config if tools_config is not None else self._subagent_tools_config()
        ctx = ToolContext(
            config=cfg,
            workspace=str(root.resolve()),
            exec_session_manager=exec_manager or self._exec_session_manager,
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
        if self._closed or self._at_capacity():
            return ToolResult.error("Error: subagent manager is closed or at task capacity")
        session_key = session_key or f"{origin_channel}:{origin_chat_id}"
        task_id = str(uuid.uuid4())
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin: _SubagentOrigin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
            "session_key": session_key,
            "llm_usage_source": current_llm_usage_source(),
        }

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
            owner=session_key,
        )
        self._task_statuses[task_id] = status
        self._resource_owners[task_id] = status

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

        bg_task.add_done_callback(partial(self._task_done, status))

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def run_inline(
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
        """Run a subagent synchronously and return its result to the caller."""
        if runtime is None:
            runtime = self._compat_spawn_runtime()
        if temperature is not None:
            runtime = runtime.with_generation_overrides(temperature=temperature)
        if self._closed or self._at_capacity():
            return ToolResult.error("Error: subagent manager is closed or at task capacity")
        session_key = session_key or f"{origin_channel}:{origin_chat_id}"
        task_id = str(uuid.uuid4())
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin: _SubagentOrigin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
            "session_key": session_key,
            "llm_usage_source": current_llm_usage_source(),
        }
        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
            owner=session_key,
        )
        self._task_statuses[task_id] = status
        self._resource_owners[task_id] = status
        logger.info("Running inline subagent [{}]: {}", task_id, display_label)
        inline_task = asyncio.create_task(
            self._run_subagent(
                task_id,
                task,
                display_label,
                origin,
                status,
                runtime,
                origin_message_id,
                workspace_scope,
                announce=False,
            )
        )
        self._running_tasks[task_id] = inline_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)
        inline_task.add_done_callback(partial(self._task_done, status))
        try:
            result = await asyncio.shield(inline_task)
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if inline_task.cancelled() and caller is not None and not caller.cancelling():
                return ToolResult.error("Task cancelled.")
            await self._cancel_task(task_id, suppress_notice=True)
            raise
        if status.phase == "error" or status.stop_reason == "error":
            return ToolResult.error(result)
        return result

    def _task_done(self, status: SubagentStatus, task: asyncio.Task[str]) -> None:
        self._running_tasks.pop(status.task_id, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Subagent [{}] failed: {}", status.task_id, error)
        self._finish(status, "cancelled", "Task cancelled.")

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: _SubagentOrigin,
        status: SubagentStatus,
        runtime: LLMRuntime,
        origin_message_id: str | None = None,
        workspace_scope: WorkspaceScope | None = None,
        *,
        announce: bool = True,
    ) -> str:
        """Wait for capacity, then execute one subagent task."""
        status.begun = True
        try:
            if status.state == "stopping":
                raise asyncio.CancelledError
            async with self._run_slots:
                if status.state == "stopping":
                    raise asyncio.CancelledError
                status.state = "running"
                status.phase = "initializing"
                result = await self._run_admitted_subagent(
                    task_id, task, label, origin, status, runtime,
                    origin_message_id, workspace_scope,
                )
                status.raise_if_stopping()
                final_state = "error" if status.stop_reason == "error" else "done"
        except asyncio.CancelledError:
            result, final_state = "Task cancelled.", "cancelled"
            status.stop_reason = "cancelled"
        except Exception as exc:
            logger.exception("Subagent [{}] failed", task_id)
            result, final_state = f"Error: {exc}", "error"
            status.error = str(exc)[:self.max_tool_result_chars]
            status.stop_reason = "error"
        # Stop acceptance before yielding for resource cleanup or notification.
        status.state = status.phase = "stopping"
        try:
            await asyncio.shield(self._start_cleanup(status))
        except Exception as exc:
            logger.exception("Subagent [{}] exec cleanup failed", task_id)
            final_state = "error"
            result = f"Error cleaning up task processes: {exc}"
            status.error = result[:self.max_tool_result_chars]
            status.stop_reason = "error"
        self._finish(status, final_state, result)
        if announce and not status.suppress_notice and not self._closed:
            await self._announce_result(
                task_id, label, task, result, origin,
                "ok" if final_state == "done" else final_state, origin_message_id,
                receipts=dict(status.receipts),
            )
        if final_state == "cancelled":
            raise asyncio.CancelledError
        return result

    async def _run_admitted_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: _SubagentOrigin,
        status: SubagentStatus,
        runtime: LLMRuntime,
        origin_message_id: str | None = None,
        workspace_scope: WorkspaceScope | None = None,
    ) -> str:
        """Execute the admitted task with task-owned shell resources."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        async def _on_checkpoint(payload: dict[str, Any]) -> None:
            if status.state == "stopping":
                raise asyncio.CancelledError
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)

        try:
            root = workspace_scope.project_path if workspace_scope is not None else self.workspace
            cfg = None
            if workspace_scope is not None:
                cfg = self._subagent_tools_config()
                cfg.restrict_to_workspace = workspace_scope.restrict_to_workspace
            # Construct from the agent workspace; the bound scope below supplies the project cwd.
            tools = self._build_tools(tools_config=cfg, exec_manager=status.exec_manager)
            system_prompt = self._build_subagent_prompt(workspace=root)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            sess_key = origin.get("session_key")
            request_token = bind_request_context(RequestContext(
                channel=origin["channel"],
                chat_id=origin["chat_id"],
                message_id=origin_message_id,
                session_key=f"subagent:{task_id}",
                runtime=runtime,
            ))
            token = bind_workspace_scope(workspace_scope) if workspace_scope is not None else None
            try:
                tool_definitions = tools.get_definitions()
                consolidate_history = partial(
                    self.consolidator.summarize_transcript,
                    runtime=runtime,
                    session_key=f"subagent:{task_id}",
                    tools=tool_definitions,
                    persist=False,
                )
                consolidate_provider_compaction = partial(
                    self.consolidator.summarize_provider_compaction,
                    runtime=runtime,
                    session_key=f"subagent:{task_id}",
                    tools=tool_definitions,
                    persist=False,
                )
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
                    checkpoint_callback=_on_checkpoint,
                    injection_callback=partial(self._drain_inbox, status),
                    session_key=sess_key,
                    workspace=root,
                    llm_usage_source=origin.get(
                        "llm_usage_source",
                        current_llm_usage_source(),
                    ),
                    consolidate_history=consolidate_history,
                    consolidate_provider_compaction=consolidate_provider_compaction,
                ))
            finally:
                if token is not None:
                    reset_workspace_scope(token)
                reset_request_context(request_token)
            status.stop_reason = result.stop_reason
            status.error = result.error

            if result.stop_reason == "error":
                final_result = result.error or "Error: subagent execution failed."
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                logger.info("Subagent [{}] completed successfully", task_id)
            return final_result

        except Exception as e:
            status.stop_reason = "error"
            status.error = str(e)[:self.max_tool_result_chars]
            logger.exception("Subagent [{}] failed", task_id)
            final_result = f"Error: {e}"
            return final_result

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: _SubagentOrigin,
        status: str,
        origin_message_id: str | None = None,
        *,
        receipts: dict[str, str] | None = None,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = {"ok": "completed successfully", "cancelled": "was cancelled"}.get(status, "failed")

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
        metadata["subagent_message_receipts"] = receipts or {}
        if receipts:
            announce_content += "\nMessage receipts: " + json.dumps(receipts)
        if origin_message_id:
            metadata["origin_message_id"] = origin_message_id
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

    def _build_subagent_prompt(self, workspace: Path | None = None) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.skills import SkillsLoader

        agent_workspace = self.workspace.expanduser().resolve()
        project_workspace = workspace.expanduser().resolve() if workspace else agent_workspace
        skills_summary = SkillsLoader(
            self.workspace,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary(workspace=project_workspace)
        history_log = (
            str(agent_workspace / "memory" / "history.jsonl")
            if agent_workspace != project_workspace
            else "memory/history.jsonl"
        )
        return render_template(
            "agent/subagent_system.md",
            workspace=str(project_workspace),
            agent_workspace=str(agent_workspace),
            history_log=history_log,
            skills_summary=skills_summary or "",
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tids = [tid for tid in self._session_tasks.get(session_key, ())
                if tid in self._running_tasks and not self._running_tasks[tid].done()]
        # Suppress every notice before cancellation can yield to a sibling.
        for tid in tids:
            self._task_statuses[tid].suppress_notice = True
        await asyncio.gather(*(self._cancel_task(tid, suppress_notice=True) for tid in tids))
        return len(tids)

    async def close(self) -> None:
        """Request cancellation and bounded cleanup, retaining unfinished work."""
        self._closed = True
        await asyncio.gather(*(self._cancel_task(tid, suppress_notice=True)
                               for tid in list(self._running_tasks)))
        cleanups: set[asyncio.Task[int]] = set()
        for status in list(self._resource_owners.values()):
            cleanup = status.cleanup_task
            if cleanup is not None and cleanup.done():
                status.cleanup_task = None
            cleanups.add(self._start_cleanup(status))
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._exec_session_manager.close_all())
        cleanups.add(self._close_task)
        done, _ = await asyncio.wait(cleanups, timeout=self.CANCEL_WAIT_SECONDS)
        for task in done:
            task.result()
        if self._running_tasks or self._resource_owners:
            logger.warning("Subagent shutdown returned with tasks or cleanup still pending")

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
