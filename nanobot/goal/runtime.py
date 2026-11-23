"""Authorization and in-run guidance for sustained goals."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nanobot.agent.goal_permission import GoalInputScope
from nanobot.session.goal_state import goal_state_runtime_lines, sustained_goal_active

if TYPE_CHECKING:
    from nanobot.session.state import SessionState

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
    def __init__(self, state: SessionState) -> None:
        self._state = state

    def scope(
        self, session_key: str | None, generation: str | None, *, persistent: bool,
    ) -> GoalExecutionScope:
        return GoalExecutionScope(self._state, session_key, generation, persistent=persistent)
