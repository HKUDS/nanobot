"""Subagent manager for background task execution."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
import warnings
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.subagent_sessions import SubagentSessions
from nanobot.agent.subagent_status import SubagentState as SubagentState
from nanobot.agent.subagent_status import SubagentStatus
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
from nanobot.providers.base import LLMProvider, ToolCallRequest
from nanobot.security.workspace_access import (
    WorkspaceScope,
    bind_workspace_scope,
    reset_workspace_scope,
    workspace_sandbox_status,
)
from nanobot.session.manager import Session, SessionManager, SessionPolicy
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.memory import Consolidator


class _SubagentOrigin(TypedDict):
    channel: str
    chat_id: str
    session_key: str | None
    llm_usage_source: NotRequired[LLMUsageSource]




class SubagentControlError(ValueError):
    """A task control request violates ownership or admission rules."""


class SubagentMessageReceipt(TypedDict):
    task_id: str
    message_id: str
    receipt: Literal["accepted"]
    delivered: Literal[False]


@dataclass(frozen=True, slots=True)
class _SubagentOutcome:
    """Execution outcome, independent of process cleanup errors."""

    state: Literal["done", "incomplete", "error", "cancelled"]
    result: str
    stop_reason: str | None = None
    error: str | None = None


@dataclass(slots=True)
class _SubagentTask:
    """Own one execution, its inbox, and resources until cleanup succeeds."""

    status: SubagentStatus
    session: Session
    runtime: LLMRuntime
    origin: _SubagentOrigin
    origin_message_id: str | None = None
    workspace_scope: WorkspaceScope | None = None
    announce: bool = True
    begun: bool = False
    suppress_notice: bool = False
    inbox: list[tuple[str, str]] = field(default_factory=list)
    outcome: _SubagentOutcome | None = None
    exec_manager: ExecSessionManager = field(default_factory=ExecSessionManager)
    cleanup_task: asyncio.Task[int] | None = None

    def raise_if_stopping(self) -> None:
        if self.outcome is not None:
            raise asyncio.CancelledError

    def decide(self, outcome: _SubagentOutcome) -> bool:
        """Seal execution once, before cancellation or cleanup can yield."""
        if self.outcome is not None:
            return False
        self.outcome = outcome
        self.status.state = self.status.phase = "stopping"
        return True

    def finish(self, max_chars: int, cleanup_error: str | None = None) -> _SubagentOutcome:
        execution_outcome = self.outcome
        if execution_outcome is None:
            raise RuntimeError("cannot finish a task before execution has an outcome")
        outcome = execution_outcome
        if cleanup_error is not None:
            outcome = _SubagentOutcome("error", cleanup_error, "error", cleanup_error)
        status = self.status
        has_partial_result = outcome.state != "done" and bool(status.result)
        if outcome.state != "done" and status.result:
            outcome = replace(outcome, result=status.result)
        status.state = status.phase = outcome.state
        status.finished_at = time.monotonic()
        status.completed_at = time.time()
        status.result = outcome.result[:max_chars]
        status.partial = has_partial_result
        status.stop_reason = outcome.stop_reason
        status.error = outcome.error[:max_chars] if outcome.error else None
        status.task_description = status.task_description[:max_chars]
        status.label = status.label[:256]
        status.tool_events = []
        for message_id, _ in self.inbox:
            status.receipts[message_id] = "undelivered"
        self.inbox.clear()
        # Failed cleanup can retain this task after its public status is evicted.
        self.outcome = replace(
            execution_outcome,
            result=execution_outcome.result[:max_chars],
            error=execution_outcome.error[:max_chars] if execution_outcome.error else None,
        )
        return outcome

    def snapshot(self) -> SubagentStatus:
        return deepcopy(self.status)


class _SubagentHook(AgentHook):
    """Hook for subagent execution — logs tool calls and updates status."""

    def __init__(self, task_id: str, status: SubagentStatus | None = None,
                 *, check_active: Callable[[], None] | None = None,
                 max_result_chars: int = 16000,
                 on_status: Callable[[SubagentStatus], None] | None = None,
                 session: Session | None = None) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status
        self._check_active = check_active
        self._max_result_chars = max_result_chars
        self._on_status = on_status
        self._session = session

    def _remember_output(self, context: AgentHookContext) -> None:
        if self._session is not None and context.messages:
            self._session.messages = deepcopy([
                message for message in context.messages if message.get("role") != "system"
            ])
        if self._status is None or context.error or context.response is None:
            return
        content = context.response.content
        if content and content.strip():
            self._status.result = content[:self._max_result_chars]
            self._status.partial = True

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        self._remember_output(context)
        if self._status is not None:
            self._status.tool_events = [
                {"name": call.name, "status": "running"} for call in context.tool_calls
            ]
        if self._status is not None and self._on_status is not None:
            self._on_status(self._status)
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
        if self._check_active is not None:
            self._check_active()

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = context.usage
        self._remember_output(context)
        if context.error:
            self._status.error = str(context.error)
        if self._on_status is not None:
            self._on_status(self._status)


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
        session_manager: SessionManager | None = None,
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
        self._tasks: dict[str, _SubagentTask] = {}
        self._terminal_statuses: dict[str, SubagentStatus] = {}
        self._closed = False
        self._close_task: asyncio.Task[int] | None = None
        self.sessions = SubagentSessions(session_manager) if session_manager is not None else None

    MAX_ACTIVE = 128
    MAX_TERMINAL = 128
    MAX_INBOX = 16
    MAX_MESSAGES = 128
    MAX_MESSAGE_BYTES = 8192

    CANCEL_WAIT_SECONDS = 5.0

    def _save_status(
        self, status: SubagentStatus, *, fsync: bool = False,
    ) -> None:
        if self.sessions is not None:
            self.sessions.save(status, fsync=fsync)

    def recover_interrupted(self) -> None:
        """Recover observations only after the host has claimed execution ownership."""
        if self.sessions is not None:
            self.sessions.interrupt_pending()

    def _start_cleanup(self, record: _SubagentTask, *, retry: bool = False) -> asyncio.Task[int]:
        cleanup = record.cleanup_task
        if retry and cleanup is not None and cleanup.done():
            record.cleanup_task = None
        if record.cleanup_task is None:
            record.cleanup_task = asyncio.create_task(record.exec_manager.close_all())
            record.cleanup_task.add_done_callback(partial(self._cleanup_done, record))
        return record.cleanup_task

    def _cleanup_done(self, record: _SubagentTask, task: asyncio.Task[int]) -> None:
        if not task.cancelled() and task.exception() is None:
            self._release_task(record)

    def _release_task(self, record: _SubagentTask) -> None:
        cleanup = record.cleanup_task
        if (record.status.finished_at is not None
                and record.status.task_id not in self._running_tasks
                and cleanup is not None and cleanup.done()
                and not cleanup.cancelled() and cleanup.exception() is None):
            self._tasks.pop(record.status.task_id, None)

    def _finish(self, record: _SubagentTask,
                cleanup_error: str | None = None) -> _SubagentOutcome:
        outcome = record.finish(self.max_tool_result_chars, cleanup_error)
        self._save_status(record.status, fsync=True)
        self._terminal_statuses[record.status.task_id] = record.snapshot()
        while len(self._terminal_statuses) > self.MAX_TERMINAL:
            del self._terminal_statuses[next(iter(self._terminal_statuses))]
        return outcome

    async def _drain_inbox(self, record: _SubagentTask) -> list[dict[str, str]]:
        record.raise_if_stopping()
        snapshot, record.inbox = record.inbox, []
        for message_id, _ in snapshot:
            record.status.receipts[message_id] = "delivered"
        if snapshot:
            self._save_status(record.status)
        return [{"role": "user", "content": content} for _, content in snapshot]

    def _owned_status(self, task_id: str, owner: str | None) -> SubagentStatus:
        status = self._terminal_statuses.get(task_id)
        record = self._tasks.get(task_id)
        if status is None and record is not None and record.status.finished_at is None:
            status = record.status
        if self.sessions is not None and owner:
            if not self.sessions.exists(owner) or not self.sessions.contains(task_id, owner):
                raise SubagentControlError("task unavailable")
            if status is None:
                status = self.sessions.status(task_id, owner)
        if not owner or status is None or status.owner != owner:
            raise SubagentControlError("task unavailable")
        return status

    def check(self, task_id: str, owner: str | None) -> SubagentStatus:
        """Return detached status for one task owned by the caller's session."""
        return deepcopy(self._owned_status(task_id, owner))

    def send(self, task_id: str, owner: str | None,
             message: str | None) -> SubagentMessageReceipt:
        """Accept a bounded follow-up only while execution is open."""
        status = self._owned_status(task_id, owner)
        if status.state not in {"queued", "running"}:
            raise SubagentControlError("task is not accepting messages")
        if not message or not message.strip() or len(message.encode("utf-8")) > self.MAX_MESSAGE_BYTES:
            raise SubagentControlError("message must contain text and be at most 8192 UTF-8 bytes")
        record = self._tasks[task_id]
        if len(record.inbox) >= self.MAX_INBOX or len(status.receipts) >= self.MAX_MESSAGES:
            raise SubagentControlError("task message capacity reached")
        message_id = str(uuid.uuid4())
        record.inbox.append((message_id, message))
        status.receipts[message_id] = "accepted"
        self._save_status(status)
        return {"task_id": task_id, "message_id": message_id,
                "receipt": "accepted", "delivered": False}

    async def cancel(self, task_id: str, owner: str | None) -> SubagentStatus:
        """Stop an owned task and return its detached state after the bounded wait."""
        status = self._owned_status(task_id, owner)
        record = self._tasks.get(task_id)
        if record is not None and record.status.finished_at is None:
            await self._cancel_task(record)
            status = record.status
        return deepcopy(status)

    async def _cancel_task(self, record: _SubagentTask,
                           *, suppress_notice: bool = False) -> None:
        record.suppress_notice |= suppress_notice
        task_id = record.status.task_id
        task = self._running_tasks.get(task_id)
        if record.decide(_SubagentOutcome("cancelled", "Task cancelled.", "cancelled")):
            self._save_status(record.status, fsync=True)
            if task is not None and record.begun and not task.done():
                task.cancel()
        if record.status.finished_at is None:
            self._start_cleanup(record)
        if task is not None:
            # wait_for waits for cancellation acknowledgement and can hang here.
            # Keep resistant work tracked, with its slot held, until it really exits.
            await asyncio.wait({task}, timeout=self.CANCEL_WAIT_SECONDS)

    def runtime_statuses(self) -> Mapping[str, SubagentStatus]:
        """Return detached active and retained terminal data, never task resources."""
        return {
            **{tid: record.snapshot() for tid, record in self._tasks.items()
               if record.status.finished_at is None},
            **deepcopy(self._terminal_statuses),
        }

    def statuses_for_session(
        self, session_key: str | None, *, include_history: bool = True,
    ) -> Mapping[str, SubagentStatus]:
        """Return only tasks owned by the given session, never a global fallback."""
        if not session_key or (self.sessions is not None and not self.sessions.exists(session_key)):
            return {}
        return {
            **(self.sessions.load(session_key) if include_history and self.sessions is not None else {}),
            **{tid: record.snapshot() for tid, record in self._tasks.items()
               if record.status.owner == session_key and record.status.finished_at is None
               and (self.sessions is None or self.sessions.contains(tid, session_key))},
            **{tid: deepcopy(status) for tid, status in self._terminal_statuses.items()
               if status.owner == session_key
               and (self.sessions is None or self.sessions.contains(tid, session_key))},
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

    def _create_task(
        self, task: str, label: str | None, origin_channel: str, origin_chat_id: str,
        session_key: str | None, origin_message_id: str | None,
        temperature: float | None, workspace_scope: WorkspaceScope | None,
        runtime: LLMRuntime | None, *, announce: bool, origin_turn_id: str | None,
    ) -> _SubagentTask:
        if runtime is None:
            runtime = self._compat_spawn_runtime()
        if temperature is not None:
            runtime = runtime.with_generation_overrides(temperature=temperature)
        # A failed cleanup owns admission even after its status has been evicted.
        if self._closed or len(self._tasks) >= self.MAX_ACTIVE:
            raise SubagentControlError("subagent manager is closed or at task capacity")
        owner = session_key or f"{origin_channel}:{origin_chat_id}"
        task_id = str(uuid.uuid4())
        status = SubagentStatus(
            task_id=task_id,
            label=label or task[:30] + ("..." if len(task) > 30 else ""),
            task_description=task,
            started_at=time.monotonic(),
            owner=owner,
            origin_message_id=origin_message_id,
            origin_turn_id=origin_turn_id,
        )
        if self.sessions is not None:
            child = self.sessions.create(status)
        else:
            child = Session(key=SubagentSessions.key(task_id), policy=SessionPolicy(persist=False))
            child.add_message("user", task)
        record = _SubagentTask(
            status=status,
            session=child,
            runtime=runtime,
            origin={
                "channel": origin_channel, "chat_id": origin_chat_id,
                "session_key": owner, "llm_usage_source": current_llm_usage_source(),
            },
            origin_message_id=origin_message_id,
            workspace_scope=workspace_scope,
            announce=announce,
        )
        self._tasks[task_id] = record
        execution = asyncio.create_task(self._run_subagent(record))
        self._running_tasks[task_id] = execution
        execution.add_done_callback(partial(self._task_done, record))
        logger.info("Started subagent [{}]: {}", task_id, record.status.label)
        return record

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
        origin_turn_id: str | None = None,
    ) -> str:
        """Start background work and route its terminal result to the parent."""
        try:
            record = self._create_task(
                task, label, origin_channel, origin_chat_id, session_key,
                origin_message_id, temperature, workspace_scope, runtime, announce=True, origin_turn_id=origin_turn_id,
            )
        except SubagentControlError as exc:
            return ToolResult.error(f"Error: {exc}")
        status = record.status
        return f"Subagent [{status.label}] started (id: {status.task_id}). I'll notify you when it completes."

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
        origin_turn_id: str | None = None,
    ) -> str:
        """Wait for the same task lifecycle without a background notice."""
        try:
            record = self._create_task(
                task, label, origin_channel, origin_chat_id, session_key,
                origin_message_id, temperature, workspace_scope, runtime, announce=False, origin_turn_id=origin_turn_id,
            )
        except SubagentControlError as exc:
            return ToolResult.error(f"Error: {exc}")
        execution = self._running_tasks[record.status.task_id]
        try:
            result = await asyncio.shield(execution)
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if execution.cancelled() and caller is not None and not caller.cancelling():
                partial_result = record.status.result if record.status.partial else None
                return ToolResult.error(
                    "Task cancelled." + (f"\nPartial result:\n{partial_result}" if partial_result else "")
                )
            await self._cancel_task(record, suppress_notice=True)
            raise
        if record.status.state == "error":
            error = record.status.error or result
            return ToolResult.error(error + (f"\nPartial result:\n{result}" if error != result else ""))
        if record.status.state == "incomplete":
            return ToolResult.error(f"Task incomplete ({record.status.stop_reason}).\n{result}")
        return result

    def _task_done(self, record: _SubagentTask, task: asyncio.Task[str]) -> None:
        self._running_tasks.pop(record.status.task_id, None)
        error = None if task.cancelled() else task.exception()
        if error is not None:
            logger.error("Subagent [{}] failed: {}", record.status.task_id, error)
        if record.status.finished_at is None:
            # An externally cancelled execution still owns cleanup and a terminal result.
            record.decide(
                _SubagentOutcome("error", f"Error: {error}", "error", str(error))
                if error is not None
                else _SubagentOutcome("cancelled", "Task cancelled.", "cancelled")
            )
            self._start_cleanup(record)
            self._finish(record)
        self._release_task(record)

    async def _run_subagent(self, record: _SubagentTask) -> str:
        """Execute once, seal the outcome, then clean up and publish once."""
        status = record.status
        task_text, label = status.task_description, status.label
        record.begun = True
        try:
            record.raise_if_stopping()
            async with self._run_slots:
                record.raise_if_stopping()
                status.state = "running"
                status.phase = "initializing"
                self._save_status(status)
                outcome = await self._run_admitted_subagent(record)
                record.decide(outcome)
        except asyncio.CancelledError:
            record.decide(_SubagentOutcome("cancelled", "Task cancelled.", "cancelled"))
        except Exception as exc:
            logger.exception("Subagent [{}] failed", status.task_id)
            record.decide(_SubagentOutcome("error", f"Error: {exc}", "error", str(exc)))
        cleanup_error = None
        try:
            await asyncio.shield(self._start_cleanup(record))
        except Exception as exc:
            logger.exception("Subagent [{}] exec cleanup failed", status.task_id)
            cleanup_error = f"Error cleaning up task processes: {exc}"
        outcome = self._finish(record, cleanup_error)
        if record.announce and not record.suppress_notice and not self._closed:
            await self._announce_result(
                status.task_id, label, task_text, outcome.result, record.origin,
                "ok" if outcome.state == "done" else outcome.state, record.origin_message_id,
                receipts=dict(status.receipts),
                stop_reason=status.stop_reason, error=status.error, partial_result=status.partial,
            )
        if outcome.state == "cancelled":
            raise asyncio.CancelledError
        return outcome.result

    async def _run_admitted_subagent(self, record: _SubagentTask) -> _SubagentOutcome:
        """Execute the admitted task with task-owned shell resources."""
        status, origin, runtime = record.status, record.origin, record.runtime
        task_id, label = status.task_id, status.label
        origin_message_id, workspace_scope = record.origin_message_id, record.workspace_scope
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        async def _on_checkpoint(payload: dict[str, Any]) -> None:
            record.raise_if_stopping()
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)

        root = workspace_scope.project_path if workspace_scope is not None else self.workspace
        cfg = None
        if workspace_scope is not None:
            cfg = self._subagent_tools_config()
            cfg.restrict_to_workspace = workspace_scope.restrict_to_workspace
        # Construct from the agent workspace; the bound scope below supplies the project cwd.
        tools = self._build_tools(tools_config=cfg, exec_manager=record.exec_manager)
        system_prompt = self._build_subagent_prompt(workspace=root)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *record.session.get_history(),
        ]

        request_token = bind_request_context(RequestContext(
            channel=origin["channel"],
            chat_id=origin["chat_id"],
            message_id=origin_message_id,
            session_key=record.session.key,
            runtime=runtime,
            log_content=record.session.policy.log_content,
        ))
        token = bind_workspace_scope(workspace_scope) if workspace_scope is not None else None
        try:
            tool_definitions = tools.get_definitions()
            consolidate_history = partial(
                self.consolidator.summarize_transcript,
                runtime=runtime,
                session_key=record.session.key,
                tools=tool_definitions,
                persist=False,
            )
            consolidate_provider_compaction = partial(
                self.consolidator.summarize_provider_compaction,
                runtime=runtime,
                session_key=record.session.key,
                tools=tool_definitions,
                persist=False,
            )
            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                runtime=runtime,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(
                    task_id, status, check_active=record.raise_if_stopping,
                    max_result_chars=self.max_tool_result_chars,
                    on_status=self._save_status,
                    session=record.session,
                ),
                max_iterations_message="Task stopped at its iteration limit before producing a final response.",
                finalize_on_max_iterations=False,
                error_message=None,
                checkpoint_callback=_on_checkpoint,
                injection_callback=partial(self._drain_inbox, record),
                session_key=record.session.key,
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
        status.usage = result.usage
        if result.messages:
            record.session.messages = deepcopy([
                message for message in result.messages if message.get("role") != "system"
            ])
        record.session.provider_state = result.provider_state
        checkpoint = result.summary_checkpoint
        if checkpoint is not None:
            boundary = checkpoint.transcript_boundary
            if 0 <= boundary <= len(result.messages):
                insert_at = sum(message.get("role") != "system" for message in result.messages[:boundary])
                record.session.commit_summary_checkpoint(checkpoint.summary, insert_at=insert_at)
        if result.stop_reason in {"error", "empty_final_response"}:
            final_result = result.error or "Error: subagent execution failed."
            return _SubagentOutcome("error", final_result, result.stop_reason, result.error)
        if result.stop_reason == "max_iterations":
            return _SubagentOutcome("incomplete", result.final_content or "Iteration limit reached.", result.stop_reason)
        final_result = result.final_content or "Task completed but no final response was generated."
        return _SubagentOutcome("done", final_result, result.stop_reason, result.error)

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
        stop_reason: str | None = None,
        error: str | None = None,
        partial_result: bool = False,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = {
            "ok": "completed successfully", "cancelled": "was cancelled",
            "incomplete": "stopped before completing the task",
        }.get(status, "failed")

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
            stop_reason=stop_reason,
            error=error,
            partial_result=partial_result,
        )

        # Inject as system message to trigger main agent.
        # Use session_key_override to align with the main agent's effective
        # session key (which accounts for unified sessions) so the result is
        # routed to the correct pending queue (mid-turn injection) instead of
        # being dispatched as a competing independent task.
        override = origin.get("session_key") or f"{origin['channel']}:{origin['chat_id']}"
        if self.sessions is not None and (
            not self.sessions.exists(override) or not self.sessions.contains(task_id, override)
        ):
            return
        metadata: dict[str, Any] = {
            "injected_event": "subagent_result",
            "subagent_task_id": task_id,
            "subagent_state": "done" if status == "ok" else status,
            "subagent_stop_reason": stop_reason,
            "subagent_partial": partial_result,
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
            require_existing_session=True,
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
        records = [record for tid, record in self._tasks.items()
                   if record.status.owner == session_key
                   and tid in self._running_tasks and not self._running_tasks[tid].done()]
        # Suppress every notice before cancellation can yield to a sibling.
        for record in records:
            record.suppress_notice = True
        await asyncio.gather(*(self._cancel_task(record, suppress_notice=True) for record in records))
        return len(records)

    async def close(self) -> None:
        """Request cancellation and bounded cleanup, retaining unfinished work."""
        self._closed = True
        await asyncio.gather(*(self._cancel_task(self._tasks[tid], suppress_notice=True)
                               for tid in list(self._running_tasks)))
        cleanups: set[asyncio.Task[int]] = set()
        for record in list(self._tasks.values()):
            cleanup = record.cleanup_task
            retry = cleanup is not None and cleanup.done() and (
                cleanup.cancelled() or cleanup.exception() is not None
            )
            cleanups.add(self._start_cleanup(record, retry=retry))
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._exec_session_manager.close_all())
        cleanups.add(self._close_task)
        done, _ = await asyncio.wait(cleanups, timeout=self.CANCEL_WAIT_SECONDS)
        for task in done:
            task.result()
        if self._tasks:
            logger.warning("Subagent shutdown returned with tasks or cleanup still pending")

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def get_running_count_by_session(self, session_key: str) -> int:
        """Return the number of currently running subagents for a session."""
        return sum(
            1 for tid, task in self._running_tasks.items()
            if self._tasks[tid].status.owner == session_key and not task.done()
        )
