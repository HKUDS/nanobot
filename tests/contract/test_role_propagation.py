"""Seam contract tests: role-switched values propagate to LLM provider."""

from __future__ import annotations

import pytest

from nanobot.agent.turn_types import TurnState
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


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


@pytest.mark.asyncio
async def test_llm_caller_uses_override_model():
    """StreamingLLMCaller.call() uses per-call model when provided."""
    from nanobot.agent.streaming import StreamingLLMCaller

    provider = ScriptedProvider([LLMResponse(content="ok")])
    caller = StreamingLLMCaller(
        provider=provider, model="default-model", temperature=0.7, max_tokens=4096
    )
    await caller.call([], None, None, model="override-model", temperature=0.1)
    assert provider.call_log[0]["model"] == "override-model"
    assert provider.call_log[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_llm_caller_uses_defaults_when_no_override():
    """StreamingLLMCaller.call() uses construction-time defaults when no override."""
    from nanobot.agent.streaming import StreamingLLMCaller

    provider = ScriptedProvider([LLMResponse(content="ok")])
    caller = StreamingLLMCaller(
        provider=provider, model="default-model", temperature=0.7, max_tokens=4096
    )
    await caller.call([], None, None)
    assert provider.call_log[0]["model"] == "default-model"
    assert provider.call_log[0]["temperature"] == 0.7
