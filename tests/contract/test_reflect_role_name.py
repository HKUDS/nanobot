"""Test for ReflectPhase per-call role_name override."""

from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.agent.turn_types import TurnState


def test_reflect_phase_passes_role_name_to_advisor() -> None:
    """ReflectPhase.evaluate() passes per-call role_name to delegation advisor."""
    from nanobot.agent.turn_phases import ReflectPhase

    advisor = MagicMock()
    advisor.advise_reflect_phase.return_value = MagicMock(action="NONE")
    reflect = ReflectPhase(
        dispatcher=MagicMock(delegation_count=0, max_delegations=8),
        delegation_advisor=advisor,
        prompts=MagicMock(),
        role_name="default-role",
    )
    state = TurnState(messages=[], user_text="hello")
    response = MagicMock(tool_calls=[])

    reflect.evaluate(state, response, False, [], role_name="override-role")

    call_kwargs = advisor.advise_reflect_phase.call_args
    assert call_kwargs.kwargs.get("role_name") == "override-role"


def test_reflect_phase_uses_default_role_when_no_override() -> None:
    """ReflectPhase.evaluate() uses construction-time role_name when no override."""
    from nanobot.agent.turn_phases import ReflectPhase

    advisor = MagicMock()
    advisor.advise_reflect_phase.return_value = MagicMock(action="NONE")
    reflect = ReflectPhase(
        dispatcher=MagicMock(delegation_count=0, max_delegations=8),
        delegation_advisor=advisor,
        prompts=MagicMock(),
        role_name="default-role",
    )
    state = TurnState(messages=[], user_text="hello")
    response = MagicMock(tool_calls=[])

    reflect.evaluate(state, response, False, [])

    call_kwargs = advisor.advise_reflect_phase.call_args
    assert call_kwargs.kwargs.get("role_name") == "default-role"
