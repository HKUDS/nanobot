"""Tests for DelegationAdvisor — unified delegation decision point."""

from __future__ import annotations

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
