"""Turn-scoped hook assembly for agent runs."""

from __future__ import annotations

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
from nanobot.events import NO_EVENTS, EventSink


@dataclass(slots=True)
class AgentTurnHookSpec:
    """Inputs needed to build the hook chain for one agent turn."""

    events: EventSink = NO_EVENTS
    streaming: bool = False
    channel: str = "cli"
    chat_id: str = "direct"
    message_id: str | None = None
    metadata: dict[str, Any] | None = None
    session_key: str | None = None
    workspace: Path | None = None
    tool_hint_max_length: int = 40
    registered_hook_factories: list[AgentTurnHookFactory] = field(default_factory=list)
    turn_hook_factories: list[AgentTurnHookFactory] = field(default_factory=list)
    registered_hooks: list[AgentHook] = field(default_factory=list)
    turn_hooks: list[AgentHook] = field(default_factory=list)
    ephemeral: bool = False
    run_extra_hooks_for_ephemeral: bool = False
    attributes: dict[str, Any] | None = None


def build_agent_turn_hook(spec: AgentTurnHookSpec) -> AgentHook:
    """Build the hook chain used by ``AgentRunner`` for one turn."""
    progress_hook = AgentProgressHook(
        events=spec.events,
        streaming=spec.streaming,
        session_key=spec.session_key,
        tool_hint_max_length=spec.tool_hint_max_length,
    )
    if spec.ephemeral and not spec.run_extra_hooks_for_ephemeral:
        return progress_hook

    turn_context = AgentTurnHookContext(
        events=spec.events,
        workspace=spec.workspace,
        channel=spec.channel,
        chat_id=spec.chat_id,
        message_id=spec.message_id,
        session_key=spec.session_key,
        metadata=dict(spec.metadata or {}),
        attributes=dict(spec.attributes or {}),
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
