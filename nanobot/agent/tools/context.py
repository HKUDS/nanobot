"""Runtime context for tool construction."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from nanobot.config.network import NetworkConfig

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.agent.tools.file_state import FileStates
    from nanobot.agent.tools.runtime_control import RuntimeControl
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ProvidersConfig, ToolsConfig
    from nanobot.cron.service import CronService
    from nanobot.providers.factory import ProviderSnapshot
    from nanobot.security.workspace_access import WorkspaceSandboxStatus, WorkspaceScope
    from nanobot.session.manager import SessionManager
    from nanobot.utils.llm_runtime import LLMRuntime

_CURRENT_REQUEST_CONTEXT: ContextVar["RequestContext | None"] = ContextVar(
    "nanobot_tool_request_context",
    default=None,
)


@dataclass(frozen=True)
class RequestContext:
    """Per-request context injected into tools at message-processing time."""
    channel: str
    chat_id: str
    message_id: str | None = None
    session_key: str | None = None
    session_generation: str | None = field(default=None, kw_only=True)
    original_user_text: str | None = None
    runtime: LLMRuntime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sender_id: str | None = None
    turn_id: str | None = None
    workspace: Path | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    log_content: bool = True
    # The host can consume completion messages after this request returns.
    can_receive_background_results: bool = True
    persist_session: bool = True
    # Effective tool scope; injected inputs retain the active run's scope.
    workspace_scope: WorkspaceScope | None = None


@runtime_checkable
class ContextAware(Protocol):
    def set_context(self, ctx: RequestContext) -> None:
        ...


def bind_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _CURRENT_REQUEST_CONTEXT.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _CURRENT_REQUEST_CONTEXT.reset(token)


@contextmanager
def request_context(ctx: RequestContext):
    """Bind one immutable request snapshot and restore the previous value."""
    token = bind_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)


def current_request_context() -> RequestContext | None:
    return _CURRENT_REQUEST_CONTEXT.get()


def tool_log_content_allowed() -> bool:
    """Whether diagnostics may include content from the current tool request."""
    ctx = current_request_context()
    return ctx is None or ctx.log_content


def current_request_session_key() -> str | None:
    ctx = current_request_context()
    return ctx.session_key if ctx else None


_CURRENT_TOOL_INVOCATION: ContextVar["ToolInvocationContext | None"] = ContextVar(
    "nanobot_tool_invocation_context",
    default=None,
)


@dataclass(frozen=True)
class ToolInvocationContext:
    """Identity of the logical tool invocation currently being executed.

    ``tool_call_id`` is the provider's stable id for the call, the same id the
    runtime checkpoints use to tell completed work from pending work.
    ``invocation_key`` is derived from the session key and the tool call id, so
    it is stable across a retry of the same call and distinct across sessions;
    it is ``None`` when the request has no session (ephemeral/SDK use).
    """

    tool_call_id: str
    invocation_key: str | None = None


def tool_invocation_key(session_key: str | None, tool_call_id: str) -> str | None:
    """Deterministic key for one logical tool invocation, or ``None`` without a session."""
    if not session_key or not tool_call_id:
        return None
    digest = hashlib.sha256(f"{session_key}{tool_call_id}".encode("utf-8"))
    return digest.hexdigest()


def bind_tool_invocation_context(
    ctx: ToolInvocationContext,
) -> Token[ToolInvocationContext | None]:
    return _CURRENT_TOOL_INVOCATION.set(ctx)


def reset_tool_invocation_context(token: Token[ToolInvocationContext | None]) -> None:
    _CURRENT_TOOL_INVOCATION.reset(token)


@contextmanager
def tool_invocation_context(ctx: ToolInvocationContext):
    """Bind the invocation identity for one tool execution and restore the previous value."""
    token = bind_tool_invocation_context(ctx)
    try:
        yield ctx
    finally:
        reset_tool_invocation_context(token)


def current_tool_invocation_context() -> ToolInvocationContext | None:
    """The invocation being executed on this task, or ``None`` outside tool execution."""
    return _CURRENT_TOOL_INVOCATION.get()


@dataclass
class ToolContext:
    config: ToolsConfig
    workspace: str
    network: NetworkConfig = field(default_factory=NetworkConfig)
    bus: MessageBus | None = None
    subagent_manager: SubagentManager | None = None
    cron_service: CronService | None = None
    exec_session_manager: ExecSessionManager | None = None
    sessions: SessionManager | None = None
    file_state_store: FileStates | None = None
    provider_snapshot_loader: Callable[..., ProviderSnapshot] | None = None
    providers_config: ProvidersConfig | None = None
    timezone: str = "UTC"
    workspace_sandbox: WorkspaceSandboxStatus | None = None
    runtime_control: RuntimeControl | None = None
