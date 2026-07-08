"""Turn-scoped hook assembly for agent runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nanobot.agent.hook import AgentHook, CompositeHook
from nanobot.agent.progress_hook import AgentProgressHook


@dataclass(slots=True)
class AgentTurnHookSpec:
    """Inputs needed to build the hook chain for one agent turn."""

    on_progress: Callable[..., Awaitable[None]] | None = None
    on_stream: Callable[[str], Awaitable[None]] | None = None
    on_stream_end: Callable[..., Awaitable[None]] | None = None
    channel: str = "cli"
    chat_id: str = "direct"
    message_id: str | None = None
    metadata: dict[str, Any] | None = None
    session_key: str | None = None
    tool_hint_max_length: int = 40
    set_tool_context: Callable[..., None] | None = None
    on_iteration: Callable[[int], None] | None = None
    registered_hooks: list[AgentHook] = field(default_factory=list)
    turn_hooks: list[AgentHook] = field(default_factory=list)
    ephemeral: bool = False
    run_extra_hooks_for_ephemeral: bool = False


def build_agent_turn_hook(spec: AgentTurnHookSpec) -> AgentHook:
    """Build the hook chain used by ``AgentRunner`` for one turn."""
    progress_hook = AgentProgressHook(
        on_progress=spec.on_progress,
        on_stream=spec.on_stream,
        on_stream_end=spec.on_stream_end,
        channel=spec.channel,
        chat_id=spec.chat_id,
        message_id=spec.message_id,
        metadata=spec.metadata,
        session_key=spec.session_key,
        tool_hint_max_length=spec.tool_hint_max_length,
        set_tool_context=spec.set_tool_context,
        on_iteration=spec.on_iteration,
    )
    extra_hooks = [*spec.registered_hooks, *spec.turn_hooks]
    if extra_hooks and (not spec.ephemeral or spec.run_extra_hooks_for_ephemeral):
        return CompositeHook([progress_hook, *extra_hooks])
    return progress_hook
