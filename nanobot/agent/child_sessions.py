"""Execute delegated tasks in private, in-memory sessions."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nanobot.agent.context import TranscriptInput
from nanobot.agent.hook import AgentHook
from nanobot.agent.runner import AgentRunResult, CheckpointCallback
from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ToolsConfig
from nanobot.llm_usage.context import LLMUsageSource
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.session.manager import Session, SessionPolicy
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass(frozen=True)
class ChildSessionRequest:
    task: str
    runtime: LLMRuntime
    tools_config: ToolsConfig
    max_iterations: int
    hook: AgentHook
    checkpoint_callback: CheckpointCallback
    llm_usage_source: LLMUsageSource
    workspace_scope: WorkspaceScope | None = None


def build_child_tools(loop: AgentLoop, request: ChildSessionRequest) -> ToolRegistry:
    """Keep the delegated tool capability set and process ownership isolated."""
    registry = ToolRegistry()
    scope = request.workspace_scope or loop.workspace_scopes.default()
    ToolLoader().load(ToolContext(
        config=request.tools_config,
        workspace=str(loop.workspace.resolve()),
        exec_session_manager=loop._exec_session_manager,
        file_state_store=FileStates(),
        workspace_sandbox=scope.sandbox_status,
    ), registry, scope="subagent")
    return registry


async def run_child_session(loop: AgentLoop, request: ChildSessionRequest) -> AgentRunResult:
    """Use the shared loop without channel dispatch or durable session registration."""
    session = Session(
        key=f"internal:{uuid.uuid4()}",
        policy=SessionPolicy(persist=False, log_content=False, include_memory=False),
    )
    scope = request.workspace_scope or loop.workspace_scopes.default()
    transcript = TranscriptInput(
        history=[],
        current_message=render_template("agent/subagent_system.md", task=request.task),
    )
    try:
        # Admission belongs to the supervisor's child pool. Re-entering the
        # parent request gate would deadlock inline spawn when its limit is one.
        result = await loop._run_agent_loop(
            transcript,
            runtime=request.runtime,
            session=session,
            ephemeral=True,
            enable_compaction=True,
            workspace_scope=scope,
            tools=build_child_tools(loop, request),
            run_hook=request.hook,
            checkpoint_callback=request.checkpoint_callback,
            max_iterations=request.max_iterations,
            finalize_on_max_iterations=False,
            usage_source=request.llm_usage_source,
            request_context=RequestContext(
                channel="internal",
                chat_id=session.key,
                session_key=session.key,
                original_user_text=request.task,
                runtime=request.runtime,
                workspace=scope.project_path,
            ),
        )
        loop._save_turn(session, result.messages, 1, summary_checkpoint=result.summary_checkpoint)
        return result
    finally:
        loop._file_state_store.discard(session.key)
        await loop._exec_session_manager.terminate_by_owner(session.key)
