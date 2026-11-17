from __future__ import annotations

from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Self

from nanobot.bus.events import InboundMessage
from nanobot.session.automation_turns import automation_history_overrides
from nanobot.session.turn_continuation import internal_continuation_inbound

_GOAL_MUTATION_ALLOWED: ContextVar[bool] = ContextVar(
    "nanobot_goal_mutation_allowed",
    default=False,
)
_GOAL_RESUME_ALLOWED: ContextVar[bool] = ContextVar("nanobot_goal_resume_allowed", default=False)


def goal_resume_allowed() -> bool:
    return _GOAL_RESUME_ALLOWED.get()


def goal_mutation_allowed() -> bool:
    return _GOAL_MUTATION_ALLOWED.get()


def revoke_goal_mutation_permission() -> None:
    _GOAL_MUTATION_ALLOWED.set(False)
    _GOAL_RESUME_ALLOWED.set(False)


@contextmanager
def goal_mutation_permission(allowed: bool):
    """Bind goal permission for one agent-run or direct tool execution scope."""
    token = _GOAL_MUTATION_ALLOWED.set(allowed)
    try:
        yield
    finally:
        _GOAL_MUTATION_ALLOWED.reset(token)


class GoalInputScope(ExitStack):
    """Own goal authorization for fresh inputs consumed during one agent run."""

    def __enter__(self) -> Self:
        super().__enter__()
        self.enter_context(goal_mutation_permission(False))
        token = _GOAL_RESUME_ALLOWED.set(False)
        self.callback(_GOAL_RESUME_ALLOWED.reset, token)
        return self

    def consume_inputs(self, messages: Iterable[InboundMessage]) -> None:
        """Authorize consumed user requests, never queued or replayed history."""
        for message in messages:
            if self._is_user_input(message):
                _GOAL_RESUME_ALLOWED.set(True)
                if message.metadata.get("goal_requested") is True:
                    self.enter_context(goal_mutation_permission(True))

    @staticmethod
    def _is_user_input(message: InboundMessage) -> bool:
        if (
            not message.is_user_input
            or message.channel == "system"
            or message.sender_id == "subagent"
            or internal_continuation_inbound(message.metadata)
        ):
            return False
        _, automation_metadata = automation_history_overrides(message.metadata)
        return not automation_metadata
