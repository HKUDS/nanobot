"""Commit goal changes before notifying runtime observers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
from nanobot.session.state import SessionState


async def mutate_goal(
    state: SessionState,
    bus: MessageBus | None,
    context: RuntimeEventContext,
    change: Callable[[dict[str, Any]], bool],
) -> tuple[bool, dict[str, Any]]:
    """Commit and notify within the caller's shielded settlement scope."""
    changed, metadata = await state.mutate_metadata(
        context.session_key, change, expected_generation=context.session_generation,
    )
    if changed and bus is not None:
        await bus.publish(GoalStateChanged(context=context, session_metadata=metadata))
    return changed, metadata
