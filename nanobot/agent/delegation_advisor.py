"""Unified delegation decision point replacing three independent triggers.

Replaces:
- Classifier orchestration override (coordinator.py)
- Planning prompt delegation text (plan.md)
- Runtime counter nudge (loop.py:878-897)
- Budget exhaustion nudge (loop.py:835-844)

See docs/superpowers/specs/2026-03-21-delegation-advisor-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from nanobot.agent.delegation import get_delegation_depth  # noqa: F401 — used in later phases


class DelegationAction(str, Enum):
    """Possible delegation advisory actions."""

    NONE = "none"
    SOFT_NUDGE = "soft_nudge"
    HARD_NUDGE = "hard_nudge"
    HARD_GATE = "hard_gate"
    SYNTHESIZE = "synthesize"


@dataclass(slots=True, frozen=True)
class DelegationAdvice:
    """Single coherent delegation signal for one evaluation point."""

    action: DelegationAction
    reason: str
    suggested_mode: str | None = None
    remove_delegate_tools: bool = False
    suggested_roles: list[str] | None = None
    warn_ungrounded: bool = False


@dataclass(slots=True, frozen=True)
class RolePolicy:
    """Per-role delegation behavior configuration."""

    solo_tool_threshold: int = 5
    exempt_from_nudge: bool = False


_DEFAULT_POLICIES: dict[str, RolePolicy] = {
    "pm": RolePolicy(solo_tool_threshold=3),
    "general": RolePolicy(solo_tool_threshold=5),
    "code": RolePolicy(solo_tool_threshold=10),
    "research": RolePolicy(solo_tool_threshold=8),
    "writing": RolePolicy(solo_tool_threshold=6),
}

_NONE_ADVICE = DelegationAdvice(action=DelegationAction.NONE, reason="no action needed")


class DelegationAdvisor:
    """Unified delegation decision point.

    Two-phase API:
    - advise_plan_phase: called once before the agent loop
    - advise_reflect_phase: called after each tool batch
    """

    def __init__(
        self,
        *,
        role_policies: dict[str, RolePolicy] | None = None,
        default_policy: RolePolicy | None = None,
    ) -> None:
        self._policies = {**_DEFAULT_POLICIES, **(role_policies or {})}
        self._default_policy = default_policy or RolePolicy()

    def _get_policy(self, role_name: str) -> RolePolicy:
        return self._policies.get(role_name, self._default_policy)
