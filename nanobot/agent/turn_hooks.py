"""Turn-scoped hook assembly for agent runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import (
    AgentHook,
    AgentTurnHookContext,
    AgentTurnHookFactory,
    CompositeHook,
)
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
    workspace: Path | None = None
    tool_hint_max_length: int = 40
    set_tool_context: Callable[..., None] | None = None
    on_iteration: Callable[[int], None] | None = None
    registered_hook_factories: list[AgentTurnHookFactory] = field(default_factory=list)
    turn_hook_factories: list[AgentTurnHookFactory] = field(default_factory=list)
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
    if spec.ephemeral and not spec.run_extra_hooks_for_ephemeral:
        return progress_hook

    turn_context = AgentTurnHookContext(
        on_progress=spec.on_progress,
        workspace=spec.workspace,
        channel=spec.channel,
        chat_id=spec.chat_id,
        message_id=spec.message_id,
        session_key=spec.session_key,
        metadata=dict(spec.metadata or {}),
        ephemeral=spec.ephemeral,
    )
    hook_chain: list[AgentHook] = [progress_hook]

    for factory in spec.registered_hook_factories:
        try:
            created_hook = factory(turn_context)
        except Exception:
            logger.exception("Agent turn hook factory failed: {}", factory)
            continue
        if created_hook is not None:
            hook_chain.append(created_hook)

    hook_chain.extend(spec.registered_hooks)

    for factory in spec.turn_hook_factories:
        try:
            created_hook = factory(turn_context)
        except Exception:
            logger.exception("Agent turn hook factory failed: {}", factory)
            continue
        if created_hook is not None:
            hook_chain.append(created_hook)

    hook_chain.extend(spec.turn_hooks)
    return CompositeHook(hook_chain) if len(hook_chain) > 1 else progress_hook
