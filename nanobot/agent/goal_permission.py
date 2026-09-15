"""Turn-local permission for explicit sustained-goal mutations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _GoalMutationGrant:
    allowed: bool
    active: bool = True


_GOAL_MUTATION_GRANT: ContextVar[_GoalMutationGrant | None] = ContextVar(
    "nanobot_goal_mutation_grant", default=None
)


def goal_mutation_allowed() -> bool:
    grant = _GOAL_MUTATION_GRANT.get()
    return grant is not None and grant.allowed and grant.active


def revoke_goal_mutation_permission() -> None:
    grant = _GOAL_MUTATION_GRANT.get()
    if grant is not None:
        grant.active = False
    _GOAL_MUTATION_GRANT.set(None)


@contextmanager
def goal_mutation_permission(allowed: bool):
    """Bind goal permission for one agent-run or direct tool execution scope."""
    grant = _GoalMutationGrant(allowed=allowed)
    token = _GOAL_MUTATION_GRANT.set(grant)
    try:
        yield
    finally:
        grant.active = False
        _GOAL_MUTATION_GRANT.reset(token)
