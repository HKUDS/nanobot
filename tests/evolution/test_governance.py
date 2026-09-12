from __future__ import annotations

from nanobot.evolution.governance import EvolutionPolicy


def test_forbidden_change_is_never_allowed() -> None:
    decision = EvolutionPolicy(mode="controlled", auto_apply_max_risk=1).evaluate(
        {
            "change_type": "self_grant_permission",
            "risk": 0,
        }
    )

    assert decision.allowed is False
    assert decision.auto_applicable is False


def test_observe_mode_never_auto_applies() -> None:
    decision = EvolutionPolicy(mode="observe", auto_apply_max_risk=0).evaluate(
        {
            "change_type": "procedure_checklist",
            "risk": 0,
        }
    )

    assert decision.allowed is True
    assert decision.auto_applicable is False


def test_high_risk_candidate_requires_approval() -> None:
    decision = EvolutionPolicy(mode="controlled", auto_apply_max_risk=1).evaluate(
        {
            "change_type": "behavior_change",
            "risk": 2,
        }
    )

    assert decision.allowed is True
    assert decision.auto_applicable is False


def test_unknown_change_type_cannot_be_auto_promoted() -> None:
    decision = EvolutionPolicy(mode="controlled", auto_apply_max_risk=1).evaluate(
        {
            "change_type": "invented_low_risk_label",
            "risk": 0,
        }
    )

    assert decision.allowed is True
    assert decision.auto_applicable is False
