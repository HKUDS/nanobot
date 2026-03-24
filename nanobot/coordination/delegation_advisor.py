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

from nanobot.coordination.delegation import get_delegation_depth
from nanobot.coordination.task_types import has_parallel_structure


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

    def advise_plan_phase(
        self,
        *,
        role_name: str,
        needs_orchestration: bool,
        relevant_roles: list[str],
        user_text: str,
        delegate_tools_available: bool,
    ) -> DelegationAdvice:
        """Called once before the agent loop starts."""
        if not delegate_tools_available:
            return _NONE_ADVICE

        if get_delegation_depth() > 0:
            return _NONE_ADVICE

        if needs_orchestration or len(relevant_roles) >= 2:
            if has_parallel_structure(user_text):
                return DelegationAdvice(
                    action=DelegationAction.SOFT_NUDGE,
                    reason="orchestration needed with parallel structure",
                    suggested_mode="delegate_parallel",
                    suggested_roles=relevant_roles or None,
                )
            return DelegationAdvice(
                action=DelegationAction.SOFT_NUDGE,
                reason="orchestration needed",
                suggested_mode="delegate",
                suggested_roles=relevant_roles or None,
            )

        return _NONE_ADVICE

    def advise_reflect_phase(
        self,
        *,
        role_name: str,
        turn_tool_calls: int,
        delegation_count: int,
        max_delegations: int,
        had_delegations_this_batch: bool,
        used_sequential_delegate: bool,
        has_parallel_structure: bool,
        any_ungrounded: bool,
        any_failed: bool,
        iteration: int,
        previous_advice: DelegationAction | None = None,
    ) -> DelegationAdvice:
        """Called after each tool batch in the reflect phase."""
        if get_delegation_depth() > 0:
            return _NONE_ADVICE

        if any_failed:
            return _NONE_ADVICE

        if had_delegations_this_batch:
            advice: DelegationAdvice
            if any_ungrounded:
                advice = DelegationAdvice(
                    action=DelegationAction.SYNTHESIZE,
                    warn_ungrounded=True,
                    reason="delegation complete, ungrounded results detected",
                )
            elif delegation_count >= max_delegations:
                advice = DelegationAdvice(
                    action=DelegationAction.SYNTHESIZE,
                    remove_delegate_tools=True,
                    reason="budget exhausted after delegation batch",
                )
            else:
                advice = _NONE_ADVICE

            if used_sequential_delegate and has_parallel_structure:
                advice = DelegationAdvice(
                    action=DelegationAction.SOFT_NUDGE,
                    suggested_mode="delegate_parallel",
                    reason="parallel structure detected, switch to delegate_parallel",
                )

            return advice

        if delegation_count >= max_delegations:
            return DelegationAdvice(
                action=DelegationAction.HARD_GATE,
                remove_delegate_tools=True,
                reason="delegation budget exhausted",
            )

        policy = self._get_policy(role_name)
        if policy.exempt_from_nudge:
            return _NONE_ADVICE

        if turn_tool_calls >= policy.solo_tool_threshold:
            if previous_advice == DelegationAction.SOFT_NUDGE:
                return DelegationAdvice(
                    action=DelegationAction.HARD_NUDGE,
                    reason=f"escalation: {turn_tool_calls} solo calls, soft nudge was ignored",
                )
            return DelegationAdvice(
                action=DelegationAction.SOFT_NUDGE,
                reason=f"{turn_tool_calls} solo calls without delegation",
            )

        return _NONE_ADVICE
