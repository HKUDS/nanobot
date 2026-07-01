"""Delegate tool for handing a task to a registered peer agent (A2A, see #4179)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from nanobot.agent.subagent import current_delegation_depth
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.security.workspace_access import current_workspace_scope

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        peer=StringSchema("Name of the registered peer agent to delegate to"),
        task=StringSchema("The task for the peer agent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        required=["peer", "task"],
    )
)
class DelegateTool(Tool, ContextAware):
    """Delegate a task to a named peer agent within the same server/gateway.

    Unlike ``spawn`` (which runs a generic background subagent), ``delegate``
    routes work to a *registered* peer that assumes a distinct role (its own
    system prompt and model). Chained delegation (A→B→C) is bounded by the
    manager's ``max_delegation_depth`` to prevent runaway cross-delegation.
    """

    # Available to peer subagents too, so a peer can re-delegate down the chain.
    _scopes: set[str] = {"core", "subagent"}

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel: ContextVar[str] = ContextVar("delegate_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("delegate_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("delegate_session_key", default="cli:direct")
        self._origin_message_id: ContextVar[str | None] = ContextVar(
            "delegate_origin_message_id",
            default=None,
        )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        manager = getattr(ctx, "subagent_manager", None)
        return bool(manager is not None and getattr(manager, "peers", None))

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(manager=ctx.subagent_manager)

    def set_context(self, ctx: RequestContext) -> None:
        """Set the origin context for peer announcements."""
        self._origin_channel.set(ctx.channel)
        self._origin_chat_id.set(ctx.chat_id)
        self._session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")
        self._origin_message_id.set(ctx.message_id)

    @property
    def name(self) -> str:
        return "delegate"

    def _roster(self) -> str:
        lines = []
        for peer in self._manager.peers.values():
            role = f" — {peer.role}" if peer.role else ""
            lines.append(f"{peer.name}{role}")
        return "; ".join(lines)

    @property
    def description(self) -> str:
        roster = self._roster() or "(none configured)"
        return (
            "Delegate a task to a registered peer agent that has its own role. "
            "Use this to collaborate with specialized teammates instead of doing "
            "everything yourself. The peer works independently and reports back "
            f"when done. Available peers: {roster}."
        )

    async def execute(
        self,
        peer: str,
        task: str,
        label: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Delegate the given task to a named peer agent."""
        depth = current_delegation_depth()
        max_depth = self._manager.max_delegation_depth
        if depth >= max_depth:
            return (
                f"Cannot delegate: maximum delegation depth reached "
                f"(depth {depth}/{max_depth}). Complete this task directly "
                f"instead of handing it off further."
            )

        if peer not in self._manager.peers:
            available = ", ".join(self._manager.peers) or "(none)"
            return (
                f"Cannot delegate: unknown peer '{peer}'. "
                f"Available peers: {available}."
            )

        running = self._manager.get_running_count()
        limit = self._manager.max_concurrent_subagents
        if running >= limit:
            return (
                f"Cannot delegate to '{peer}': concurrency limit reached "
                f"({running}/{limit} running). Wait for a running agent "
                f"to complete before delegating again."
            )

        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            origin_message_id=self._origin_message_id.get(),
            workspace_scope=current_workspace_scope(),
            peer=peer,
            delegation_depth=depth + 1,
        )
