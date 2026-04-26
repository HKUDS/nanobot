"""Tests for configurable consolidation_ratio."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

import nanobot.agent.memory as memory_module
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import GenerationSettings, LLMResponse


def _make_loop(
    tmp_path,
    *,
    estimated_tokens: int = 0,
    context_window_tokens: int = 200,
    consolidation_ratio: float = 0.5,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (estimated_tokens, "test-counter")
    _response = LLMResponse(content="ok", tool_calls=[])
    provider.chat_with_retry = AsyncMock(return_value=_response)
    provider.chat_stream_with_retry = AsyncMock(return_value=_response)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
        consolidation_ratio=consolidation_ratio,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator._SAFETY_BUFFER = 0
    return loop


def _session_with_turns(loop: AgentLoop, *, turns: int):
    session = loop.sessions.get_or_create("cli:test")
    session.messages = []
    for i in range(turns):
        session.messages.append({"role": "user", "content": f"u{i}", "timestamp": f"2026-01-01T00:00:{i:02d}"})
        session.messages.append({"role": "assistant", "content": f"a{i}", "timestamp": f"2026-01-01T00:01:{i:02d}"})
    loop.sessions.save(session)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ratio", "context_window_tokens", "estimates", "expected_archives"),
    [
        (0.5, 200, [250, 90], 1),
        (0.1, 1000, [1200, 800, 400, 50], 2),
        (0.9, 200, [300, 175], 1),
    ],
)
async def test_consolidation_ratio_controls_target(
    tmp_path,
    monkeypatch,
    ratio: float,
    context_window_tokens: int,
    estimates: list[int],
    expected_archives: int,
) -> None:
    loop = _make_loop(
        tmp_path,
        context_window_tokens=context_window_tokens,
        consolidation_ratio=ratio,
    )
    loop.consolidator.archive = AsyncMock(return_value=True)  # type: ignore[method-assign]
    session = _session_with_turns(loop, turns=10)

    remaining_estimates = list(estimates)

    def mock_estimate(_session, *, session_summary=None):
        assert session_summary is None
        return (remaining_estimates.pop(0), "test")

    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    await loop.consolidator.maybe_consolidate_by_tokens(session)

    assert loop.consolidator.archive.await_count == expected_archives


def test_ratio_propagated_from_config_schema() -> None:
    defaults = AgentDefaults()
    assert defaults.consolidation_ratio == 0.5

    defaults = AgentDefaults.model_validate({"consolidationRatio": 0.3})
    assert defaults.consolidation_ratio == 0.3

    dumped = defaults.model_dump(by_alias=True)
    assert dumped["consolidationRatio"] == 0.3


def test_ratio_validation_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        AgentDefaults(consolidation_ratio=0.05)

    with pytest.raises(ValidationError):
        AgentDefaults(consolidation_ratio=1.0)
