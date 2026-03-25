"""Seam contract tests: role-switched values propagate to LLM provider."""

from __future__ import annotations

from nanobot.agent.turn_types import TurnState


def test_turn_state_accepts_active_fields():
    """TurnState dataclass has active_* fields with None defaults."""
    state = TurnState(messages=[], user_text="hello")
    assert state.active_model is None
    assert state.active_temperature is None
    assert state.active_max_iterations is None
    assert state.active_role_name is None

    state2 = TurnState(
        messages=[],
        user_text="hello",
        active_model="gpt-4o",
        active_temperature=0.1,
        active_max_iterations=3,
        active_role_name="code",
    )
    assert state2.active_model == "gpt-4o"
    assert state2.active_temperature == 0.1
    assert state2.active_max_iterations == 3
    assert state2.active_role_name == "code"
