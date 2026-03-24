"""Tests for DelegationAdvisor — unified delegation decision point."""

from __future__ import annotations

from unittest.mock import patch

from nanobot.coordination.delegation_advisor import (
    DelegationAction,
    DelegationAdvice,
    DelegationAdvisor,
    RolePolicy,
)


class TestDataTypes:
    def test_delegation_action_values(self):
        assert DelegationAction.NONE == "none"
        assert DelegationAction.SOFT_NUDGE == "soft_nudge"
        assert DelegationAction.HARD_NUDGE == "hard_nudge"
        assert DelegationAction.HARD_GATE == "hard_gate"
        assert DelegationAction.SYNTHESIZE == "synthesize"

    def test_delegation_advice_defaults(self):
        advice = DelegationAdvice(action=DelegationAction.NONE, reason="test")
        assert advice.suggested_mode is None
        assert advice.remove_delegate_tools is False
        assert advice.suggested_roles is None
        assert advice.warn_ungrounded is False

    def test_role_policy_defaults(self):
        policy = RolePolicy()
        assert policy.solo_tool_threshold == 5
        assert policy.exempt_from_nudge is False

    def test_advisor_default_policies(self):
        advisor = DelegationAdvisor()
        # Known roles should have non-default thresholds
        assert advisor._get_policy("code").solo_tool_threshold == 10
        assert advisor._get_policy("pm").solo_tool_threshold == 3
        assert advisor._get_policy("unknown").solo_tool_threshold == 5  # default


class TestAdvisePlanPhase:
    def _advise(self, advisor=None, **overrides):
        defaults = dict(
            role_name="general",
            needs_orchestration=False,
            relevant_roles=[],
            user_text="do something",
            delegate_tools_available=True,
        )
        defaults.update(overrides)
        return (advisor or DelegationAdvisor()).advise_plan_phase(**defaults)

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_single_domain_returns_none(self, _mock):
        advice = self._advise(needs_orchestration=False, relevant_roles=["code"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_orchestration_needed_returns_soft_nudge(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE
        assert advice.suggested_roles == ["code", "research"]

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_parallel_structure_suggests_parallel_mode(self, _mock):
        advice = self._advise(
            needs_orchestration=True,
            relevant_roles=["code", "research"],
            user_text="1. analyze code\n2. research alternatives\n3. write report",
        )
        assert advice.suggested_mode == "delegate_parallel"

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=1)
    def test_sub_agent_always_none(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "pm"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_tools_unavailable_returns_none(self, _mock):
        advice = self._advise(delegate_tools_available=False, needs_orchestration=True)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_two_relevant_roles_triggers_nudge(self, _mock):
        advice = self._advise(relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_orchestration_true_empty_roles_still_nudges(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=[])
        assert advice.action == DelegationAction.SOFT_NUDGE


class TestAdviseReflectPhase:
    def _advise(self, advisor=None, **overrides):
        defaults = dict(
            role_name="general",
            turn_tool_calls=0,
            delegation_count=0,
            max_delegations=8,
            had_delegations_this_batch=False,
            used_sequential_delegate=False,
            has_parallel_structure=False,
            any_ungrounded=False,
            any_failed=False,
            iteration=1,
            previous_advice=None,
        )
        defaults.update(overrides)
        return (advisor or DelegationAdvisor()).advise_reflect_phase(**defaults)

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=1)
    def test_delegated_agent_always_none(self, _mock):
        advice = self._advise(turn_tool_calls=20)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_budget_exhausted_hard_gate(self, _mock):
        advice = self._advise(delegation_count=8, max_delegations=8)
        assert advice.action == DelegationAction.HARD_GATE
        assert advice.remove_delegate_tools is True

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_failures_take_priority(self, _mock):
        advice = self._advise(any_failed=True, turn_tool_calls=10)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_ungrounded_warns(self, _mock):
        advice = self._advise(had_delegations_this_batch=True, any_ungrounded=True)
        assert advice.action == DelegationAction.SYNTHESIZE
        assert advice.warn_ungrounded is True

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_budget_full_synthesize(self, _mock):
        advice = self._advise(
            had_delegations_this_batch=True, delegation_count=8, max_delegations=8
        )
        assert advice.action == DelegationAction.SYNTHESIZE
        assert advice.remove_delegate_tools is True

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_sequential_with_parallel_structure_nudges(self, _mock):
        advice = self._advise(
            had_delegations_this_batch=True,
            used_sequential_delegate=True,
            has_parallel_structure=True,
        )
        assert advice.action == DelegationAction.SOFT_NUDGE
        assert advice.suggested_mode == "delegate_parallel"

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_code_role_high_threshold(self, _mock):
        advice = self._advise(role_name="code", turn_tool_calls=7)
        assert advice.action == DelegationAction.NONE  # threshold is 10

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_general_role_threshold_soft_nudge(self, _mock):
        advice = self._advise(role_name="general", turn_tool_calls=6)
        assert advice.action == DelegationAction.SOFT_NUDGE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_escalation_soft_to_hard(self, _mock):
        advice = self._advise(
            role_name="general",
            turn_tool_calls=6,
            previous_advice=DelegationAction.SOFT_NUDGE,
        )
        assert advice.action == DelegationAction.HARD_NUDGE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_exempt_role_never_nudged(self, _mock):
        advisor = DelegationAdvisor(
            role_policies={"specialist": RolePolicy(exempt_from_nudge=True)}
        )
        advice = self._advise(advisor=advisor, role_name="specialist", turn_tool_calls=20)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.coordination.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_no_special_conditions_none(self, _mock):
        """Delegation in progress, no budget/ungrounded/parallel issues -> NONE."""
        advice = self._advise(had_delegations_this_batch=True)
        assert advice.action == DelegationAction.NONE
