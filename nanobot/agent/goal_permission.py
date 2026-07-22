"""Turn-local permission for explicit sustained-goal mutations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_GOAL_MUTATION_ALLOWED: ContextVar[bool] = ContextVar(
    "nanobot_goal_mutation_allowed",
    default=False,
)


def goal_mutation_allowed() -> bool:
    return _GOAL_MUTATION_ALLOWED.get()


def revoke_goal_mutation_permission() -> None:
    _GOAL_MUTATION_ALLOWED.set(False)


@contextmanager
def goal_mutation_permission(allowed: bool):
    """Bind goal permission for one agent-run or direct tool execution scope."""
    token = _GOAL_MUTATION_ALLOWED.set(allowed)
    try:
        yield
    finally:
        _GOAL_MUTATION_ALLOWED.reset(token)
