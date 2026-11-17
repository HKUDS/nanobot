"""Authorization and in-run guidance for sustained goals."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.goal_permission import GoalInputScope
from nanobot.agent.tools.context import RequestContext
from nanobot.bus.runtime_events import RuntimeEventContext
from nanobot.goal.state import mutate_goal
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    goal_state_raw,
    goal_state_runtime_lines,
    parse_goal_state,
    sustained_goal_active,
)
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.utils.cancellation import shield_and_drain

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.session.state import SessionState

_FAILURE_RECAPS = {
    "error": "The model request failed and automatic recovery has ended.",
    "length": "The model reached its output limit and continuation attempts were exhausted.",
    "empty_final_response": "The model returned no answer after recovery attempts were exhausted.",
    "refusal": "The model refused the request.",
    "content_filter": "The model request was stopped by a content filter.",
    "tool_error": "Execution stopped after a terminal tool error.",
    "exception": "Execution stopped because of an unexpected runtime error.",
}

GOAL_GENERATION_VOLATILE_KEYS = frozenset({
    "goal_state", "thread_goal", "_sustained_goal_continuation_rounds",
})


class GoalExecutionScope(GoalInputScope):
    def __init__(
        self, state: SessionState, session_key: str | None, generation: str | None,
        *, persistent: bool,
    ) -> None:
        super().__init__()
        self._state = state
        self._session_key = session_key
        self._generation = generation
        self._persistent = persistent

    async def continuation_prompt(self) -> str | None:
        key = self._session_key
        current = await self._state.read_header(key) if key and self._persistent else None
        if current is None or current.generation != self._generation:
            return None
        if not sustained_goal_active(current.metadata):
            return None
        lines = "\n".join(goal_state_runtime_lines(current.metadata))
        return (
            f"You have an active sustained goal:\n\n{lines}\n\n"
            "Please continue working toward the objective using your tools, or call update_goal "
            "with action='complete' if the work is truly finished. "
            "If required conditions are unavailable, use action='block' with an honest recap."
        )


class GoalExecutionPolicy:
    def __init__(self, state: SessionState, bus: MessageBus | None = None) -> None:
        self._state = state
        self._bus = bus

    def scope(
        self, session_key: str | None, generation: str | None, *, persistent: bool,
    ) -> GoalExecutionScope:
        return GoalExecutionScope(self._state, session_key, generation, persistent=persistent)

    async def finish(
        self, request: RequestContext, stop_reason: str, error_kind: str | None = None,
    ) -> None:
        recap = _FAILURE_RECAPS.get(stop_reason)
        if (
            recap is None or not request.persist_session
            or not request.session_key or not request.session_generation
        ):
            return

        def block(metadata: dict[str, Any]) -> bool:
            goal = parse_goal_state(goal_state_raw(metadata))
            if goal is None or goal.get("status") != "active":
                return False
            metadata[GOAL_STATE_KEY] = {
                **goal, "status": "blocked", "ended_at": datetime.now().isoformat(),
                "blocked_reason": stop_reason, "recap": recap,
            }
            if error_kind is not None:
                metadata[GOAL_STATE_KEY]["failure_error_kind"] = error_kind
            discard_legacy_goal_state_key(metadata)
            return True

        try:
            await shield_and_drain(mutate_goal(self._state, self._bus, RuntimeEventContext(
                channel=request.channel, chat_id=request.chat_id,
                session_key=request.session_key, session_generation=request.session_generation,
                metadata=dict(request.metadata),
            ), block))
        except SessionConflictError:
            # Reset/delete retired this execution; its failure belongs to the old generation.
            return
