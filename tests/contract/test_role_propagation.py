"""Seam contract tests: LLM caller model/temperature override propagation.

Tests verify that StreamingLLMCaller accepts per-call overrides and
that the default wiring passes construction-time defaults to the provider.
"""

from __future__ import annotations

import pytest

from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider, _make_loop

# ---------------------------------------------------------------------------
# Component-level seam tests
# ---------------------------------------------------------------------------


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
