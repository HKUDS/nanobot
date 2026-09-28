"""Persist and execute delegated work in isolated, inspectable sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from nanobot.agent.context import ContextBuilder, TranscriptInput
from nanobot.agent.hook import AgentHook
from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunner, AgentRunResult, AgentRunSpec, CheckpointCallback
from nanobot.agent.session_execution import SessionExecutor
from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.file_state import FileStates, FileStateStore
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ToolsConfig
from nanobot.llm_usage.context import LLMUsageSource
from nanobot.providers.base import LLMUsage
from nanobot.security.workspace_access import WorkspaceScope, WorkspaceScopeResolver
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import RUNTIME_CHECKPOINT_KEY, restore_runtime_checkpoint
from nanobot.session.transcript import commit_turn
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template


@dataclass(frozen=True)
class ChildSessionRequest:
    task_id: str
    task: str
    runtime: LLMRuntime
    tools_config: ToolsConfig
    max_iterations: int
    hook: AgentHook
    checkpoint_callback: CheckpointCallback
    llm_usage_source: LLMUsageSource
    workspace_scope: WorkspaceScope | None = None


@dataclass
class ChildSessionService:
    """Own child session records and resources; admission belongs to the supervisor."""

    executor: SessionExecutor
    sessions: SessionManager
    exec_sessions: ExecSessionManager
    workspace_scopes: WorkspaceScopeResolver
    max_tool_result_chars: int
    provider_retry_mode: str = "standard"

    @classmethod
    def standalone(
        cls, workspace: Path, *, restrict_to_workspace: bool,
        disabled_skills: list[str], max_tool_result_chars: int,
        consolidator: Consolidator | None = None,
    ) -> ChildSessionService:
        """Build the SDK execution environment without channel or agent-loop services."""
        context = ContextBuilder(workspace, disabled_skills=disabled_skills)
        sessions = SessionManager(workspace)
        tools = ToolRegistry()
        summarizer = consolidator if consolidator is not None else Consolidator(
            store=context.memory, sessions=sessions,
            build_messages=context.build_messages, get_tool_definitions=tools.get_definitions,
        )
        return cls(
            executor=SessionExecutor(context, summarizer, AgentRunner(), FileStateStore()),
            sessions=sessions, exec_sessions=ExecSessionManager(),
            workspace_scopes=WorkspaceScopeResolver(workspace, restrict_to_workspace),
            max_tool_result_chars=max_tool_result_chars,
        )

    def create(
        self, task_id: str, task: str, label: str, parent_session_key: str | None,
        runtime: LLMRuntime, scope: WorkspaceScope | None,
    ) -> Session:
        """Record the queued task before admission so cancellation remains observable."""
        session = self.sessions.get_or_create(f"subagent:{task_id}")
        if "subagent" in session.metadata:
            return session
        scope = scope or self.workspace_scopes.default()
        session.metadata.update({
            "title": label,
            "subagent": {
                "task_id": task_id, "parent_session_key": parent_session_key,
                "status": "queued", "model": runtime.model,
                "workspace": str(scope.project_path), "access_mode": scope.access_mode,
                "created_at": datetime.now().isoformat(),
            },
        })
        session.add_message("user", render_template("agent/subagent_system.md", task=task))
        self.sessions.save(session)
        return session

    def finish(
        self, session: Session, status: Literal["completed", "failed", "cancelled"], *,
        stop_reason: str | None = None, error: str | None = None, usage: LLMUsage | None = None,
    ) -> None:
        """Commit terminal status and any interrupted tool checkpoint."""
        restore_runtime_checkpoint(session)
        session.metadata["subagent"].update(
            status=status, finished_at=datetime.now().isoformat(),
            stop_reason=stop_reason, error=error, usage=usage.to_dict() if usage else None,
        )
        self.sessions.save(session)

    def cancel(self, task_id: str) -> None:
        """Record cancellation even if the scheduled coroutine never entered."""
        session = self.sessions.get_or_create(f"subagent:{task_id}")
        if session.metadata["subagent"]["status"] in {"queued", "running"}:
            self.finish(session, "cancelled")

    def build_tools(self, request: ChildSessionRequest, scope: WorkspaceScope) -> ToolRegistry:
        registry = ToolRegistry()
        ToolLoader().load(ToolContext(
            config=request.tools_config,
            workspace=str(self.executor.context.workspace.resolve()),
            exec_session_manager=self.exec_sessions,
            file_state_store=FileStates(),
            workspace_sandbox=scope.sandbox_status,
        ), registry, scope="subagent")
        return registry

    async def run(self, request: ChildSessionRequest) -> AgentRunResult:
        session = self.sessions.get_or_create(f"subagent:{request.task_id}")
        scope = request.workspace_scope or self.workspace_scopes.default()
        session.metadata["subagent"].update(
            status="running", started_at=datetime.now().isoformat(),
        )
        self.sessions.save(session)

        async def checkpoint(payload: dict[str, Any]) -> None:
            # Provider-native state is process-local; retain the portable transcript.
            public = {key: value for key, value in payload.items() if key != "provider_state"}
            session.metadata[RUNTIME_CHECKPOINT_KEY] = public
            session.metadata["subagent"].update(
                phase=public.get("phase"), iteration=public.get("iteration"),
            )
            if public.get("phase") in {"tools_completed", "final_response"}:
                restore_runtime_checkpoint(session)
                self.sessions.save(session)
            else:
                self.sessions.save(session)
                self.sessions.save_runtime_checkpoint(session)
            await request.checkpoint_callback(public)

        try:
            try:
                result = await self.executor.run(AgentRunSpec(
                    initial_messages=None,
                    transcript_input=TranscriptInput(history=[], current_message=session.messages[0]["content"]),
                    runtime=request.runtime,
                    tools=self.build_tools(request, scope),
                    session_key=session.key,
                    workspace=scope.project_path,
                    max_iterations=request.max_iterations,
                    max_tool_result_chars=self.max_tool_result_chars,
                    hook=request.hook,
                    concurrent_tools=True,
                    checkpoint_callback=checkpoint,
                    finalize_on_max_iterations=False,
                    llm_usage_source=request.llm_usage_source,
                    provider_retry_mode=self.provider_retry_mode,
                ), request=RequestContext(
                    channel="subagent", chat_id=request.task_id, session_key=session.key,
                    original_user_text=request.task, runtime=request.runtime, workspace=scope.project_path,
                ), scope=scope, policy=session.policy)
            finally:
                self.executor.file_states.discard(session.key)
                await self.exec_sessions.terminate_by_owner(session.key)
            # Replace checkpoint projections with the runner's final canonical transcript.
            completed = Session(key=session.key)
            commit_turn(completed, result.messages, 1, summary_checkpoint=result.summary_checkpoint)
            session.messages = completed.messages
            session.last_consolidated = completed.last_consolidated
            session.metadata.update(completed.metadata)
            session.metadata.pop(RUNTIME_CHECKPOINT_KEY, None)
            self.finish(
                session, "failed" if result.stop_reason == "error" else "completed",
                stop_reason=result.stop_reason, error=result.error,
                usage=result.usage,
            )
            return result
        except asyncio.CancelledError:
            self.finish(session, "cancelled")
            raise
        except Exception as exc:
            self.finish(session, "failed", error=str(exc))
            raise
