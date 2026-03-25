"""Seam contract tests: role-switched values propagate to LLM provider.

Tests are organized in two groups:
1. Component-level seam tests — verify individual components accept overrides.
2. End-to-end pipeline tests — verify the full wiring from AgentLoop through to
   the provider, proving role switching actually changes what model is used.
"""

from __future__ import annotations

import pytest

from nanobot.agent.turn_types import TurnState
from nanobot.config.schema import AgentRoleConfig
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider, _make_loop

# ---------------------------------------------------------------------------
# Component-level seam tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# End-to-end pipeline tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_role_override_uses_defaults(tmp_path):
    """Without role switching, the provider receives construction-time defaults."""
    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    await loop.process_direct("hello")

    assert provider.call_log[0]["model"] == "test-model"
    assert provider.call_log[0]["temperature"] == 0.1  # AgentConfig default


@pytest.mark.asyncio
async def test_role_switch_propagates_model_to_provider(tmp_path):
    """After role switching, the provider receives the role's model and temperature."""
    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    role = AgentRoleConfig(name="code", description="", model="role-model", temperature=0.1)
    turn_ctx = loop._role_manager.apply(role)
    try:
        await loop.process_direct("hello")
    finally:
        loop._role_manager.reset(turn_ctx)

    assert provider.call_log[0]["model"] == "role-model"
    assert provider.call_log[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_role_reset_restores_default_model(tmp_path):
    """After role reset, the next turn uses the default model."""
    provider = ScriptedProvider(
        [
            LLMResponse(content="response1"),
            LLMResponse(content="response2"),
        ]
    )
    loop = _make_loop(tmp_path, provider)

    # Turn 1: with role override
    role = AgentRoleConfig(name="code", description="", model="role-model")
    turn_ctx = loop._role_manager.apply(role)
    await loop.process_direct("turn1")
    loop._role_manager.reset(turn_ctx)

    # Turn 2: no role override — should use default
    await loop.process_direct("turn2")

    assert provider.call_log[0]["model"] == "role-model"
    assert provider.call_log[1]["model"] == "test-model"


@pytest.mark.asyncio
async def test_role_max_iterations_respected(tmp_path):
    """active_max_iterations limits the PAOR loop to the role's iteration count."""
    from nanobot.providers.base import ToolCallRequest

    # Script: tool-call responses that would loop forever without iteration limit.
    tool_call = ToolCallRequest(id="t1", name="list_dir", arguments={"path": "."})
    provider = ScriptedProvider(
        [
            LLMResponse(content=None, tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[tool_call]),
            LLMResponse(content="final"),
        ]
    )
    loop = _make_loop(tmp_path, provider)

    state = TurnState(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        user_text="hello",
        active_max_iterations=1,
        tools_def_cache=list(loop._processor.tools.get_definitions()),
    )
    result = await loop._processor.orchestrator.run(state, None)

    # With max_iterations=1, the loop should stop after 1 iteration.
    assert "maximum number of tool call iterations (1)" in result.content
    assert result.llm_calls <= 1


@pytest.mark.asyncio
async def test_orchestrator_passes_active_model_to_llm_caller(tmp_path):
    """TurnOrchestrator reads active_model from TurnState and passes to LLM caller."""
    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    state = TurnState(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        user_text="hello",
        active_model="role-specific-model",
        active_temperature=0.1,
        tools_def_cache=[],
    )
    await loop._processor.orchestrator.run(state, None)

    assert provider.call_log[0]["model"] == "role-specific-model"
    assert provider.call_log[0]["temperature"] == 0.1
