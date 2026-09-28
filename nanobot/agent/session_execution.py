"""Shared context, compaction, and tool scope for one session execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunner, AgentRunResult, AgentRunSpec
from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.file_state import FileStateStore, bind_file_states, reset_file_states
from nanobot.security.workspace_access import (
    WorkspaceScope,
    bind_workspace_scope,
    reset_workspace_scope,
)
from nanobot.session.manager import SessionPolicy


@dataclass
class SessionExecutor:
    """Execute model turns without channel routing, admission, or storage ownership."""

    context: ContextBuilder
    consolidator: Consolidator
    runner: AgentRunner
    file_states: FileStateStore

    async def run(
        self,
        spec: AgentRunSpec,
        *,
        request: RequestContext,
        scope: WorkspaceScope,
        policy: SessionPolicy,
    ) -> AgentRunResult:
        request = replace(request, log_content=request.log_content and policy.log_content)
        summary_args = dict(
            runtime=spec.runtime,
            session_key=spec.session_key or "agent:transient",
            tools=spec.tools.get_definitions(),
            persist=policy.persist and policy.archive_memory,
        )
        spec = replace(
            spec,
            transcript_builder=partial(
                self.context.build_transcript,
                channel=request.channel,
                workspace=scope.project_path,
                include_memory=policy.include_memory,
            ),
            consolidate_history=partial(self.consolidator.summarize_transcript, **summary_args),
            consolidate_provider_compaction=partial(
                self.consolidator.summarize_provider_compaction, **summary_args,
            ),
        )
        file_token = bind_file_states(self.file_states.for_session(spec.session_key))
        request_token = bind_request_context(request)
        scope_token = bind_workspace_scope(scope)
        try:
            return await self.runner.run(spec)
        finally:
            reset_workspace_scope(scope_token)
            reset_request_context(request_token)
            reset_file_states(file_token)
