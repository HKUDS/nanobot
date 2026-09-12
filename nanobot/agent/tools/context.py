"""Runtime context for tool construction."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.agent.tools.file_state import FileStates
    from nanobot.agent.tools.runtime_control import RuntimeControl
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ProviderConfig, ToolsConfig
    from nanobot.cron.service import CronService
    from nanobot.providers.factory import ProviderSnapshot
    from nanobot.security.workspace_access import WorkspaceSandboxStatus
    from nanobot.session.manager import SessionManager
    from nanobot.utils.llm_runtime import LLMRuntime

_CURRENT_REQUEST_CONTEXT: ContextVar["RequestContext | None"] = ContextVar(
    "nanobot_tool_request_context",
    default=None,
)
_CURRENT_TOOL_INVOCATION_CONTEXT: ContextVar["ToolInvocationContext | None"] = ContextVar(
    "nanobot_tool_invocation_context",
    default=None,
)

_TOOL_INVOCATION_KEY_DOMAIN = "nanobot.tool.invocation.v1"


@dataclass(frozen=True)
class RequestContext:
    """Per-request context injected into tools at message-processing time."""
    channel: str
    chat_id: str
    message_id: str | None = None
    session_key: str | None = None
    original_user_text: str | None = None
    runtime: LLMRuntime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sender_id: str | None = None
    turn_id: str | None = None
    workspace: Path | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolInvocationContext:
    """Identity of the currently executing logical tool call."""

    tool_call_id: str
    invocation_key: str | None = None


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


def current_request_session_key() -> str | None:
    ctx = current_request_context()
    return ctx.session_key if ctx else None


def _derive_tool_invocation_key(tool_call_id: str) -> str | None:
    request = current_request_context()
    if request is None or not request.session_key or not tool_call_id:
        return None

    payload = json.dumps(
        [_TOOL_INVOCATION_KEY_DOMAIN, request.session_key, tool_call_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@contextmanager
def tool_invocation_context(tool_call_id: str) -> Generator[ToolInvocationContext, None, None]:
    """Bind one tool-call-local identity and restore the previous value."""
    ctx = ToolInvocationContext(
        tool_call_id=tool_call_id,
        invocation_key=_derive_tool_invocation_key(tool_call_id),
    )
    token = _CURRENT_TOOL_INVOCATION_CONTEXT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_TOOL_INVOCATION_CONTEXT.reset(token)


def current_tool_invocation_context() -> ToolInvocationContext | None:
    """Return the current tool invocation identity, if inside a tool call."""
    return _CURRENT_TOOL_INVOCATION_CONTEXT.get()


@dataclass
class ToolContext:
    config: ToolsConfig
    workspace: str
    bus: MessageBus | None = None
    subagent_manager: SubagentManager | None = None
    cron_service: CronService | None = None
    exec_session_manager: ExecSessionManager | None = None
    sessions: SessionManager | None = None
    file_state_store: FileStates | None = None
    provider_snapshot_loader: Callable[..., ProviderSnapshot] | None = None
    image_generation_provider_configs: dict[str, ProviderConfig] | None = None
    timezone: str = "UTC"
    workspace_sandbox: WorkspaceSandboxStatus | None = None
    runtime_control: RuntimeControl | None = None
