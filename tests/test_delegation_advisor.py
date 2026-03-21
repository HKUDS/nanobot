"""Tests for DelegationAdvisor — unified delegation decision point."""

from __future__ import annotations

from unittest.mock import patch

from nanobot.agent.delegation_advisor import (
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

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_single_domain_returns_none(self, _mock):
        advice = self._advise(needs_orchestration=False, relevant_roles=["code"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_orchestration_needed_returns_soft_nudge(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE
        assert advice.suggested_roles == ["code", "research"]

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_parallel_structure_suggests_parallel_mode(self, _mock):
        advice = self._advise(
            needs_orchestration=True,
            relevant_roles=["code", "research"],
            user_text="1. analyze code\n2. research alternatives\n3. write report",
        )
        assert advice.suggested_mode == "delegate_parallel"

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=1)
    def test_sub_agent_always_none(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "pm"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_tools_unavailable_returns_none(self, _mock):
        advice = self._advise(delegate_tools_available=False, needs_orchestration=True)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_two_relevant_roles_triggers_nudge(self, _mock):
        advice = self._advise(relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE
