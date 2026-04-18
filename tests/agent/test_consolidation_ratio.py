"""Tests for the configurable consolidation_ratio feature."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
import nanobot.agent.memory as memory_module
from nanobot.bus.queue import MessageBus
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


@pytest.mark.asyncio
async def test_default_ratio_uses_half_budget(tmp_path, monkeypatch) -> None:
    """With ratio=0.5 (default), target should be half of budget."""
    loop = _make_loop(tmp_path, context_window_tokens=200, consolidation_ratio=0.5)
    loop.consolidator.archive = AsyncMock(return_value=True)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
        {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
        {"role": "assistant", "content": "a3", "timestamp": "2026-01-01T00:00:05"},
        {"role": "user", "content": "u4", "timestamp": "2026-01-01T00:00:06"},
    ]
    loop.sessions.save(session)

    # budget = 200 - 0 (max_tokens) - 0 (safety_buffer) = 200
    # target = int(200 * 0.5) = 100
    # estimated must be >= budget to trigger consolidation
    call_count = [0]

    def mock_estimate(_session):
        call_count[0] += 1
        if call_count[0] == 1:
            return (250, "test")
        return (90, "test")

    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    await loop.consolidator.maybe_consolidate_by_tokens(session)

    # 250 >= 200 (budget, triggers) → 250 > 100 (target) → archive → 90 < 100, stops.
    assert loop.consolidator.archive.await_count == 1


@pytest.mark.asyncio
async def test_low_ratio_aggressively_consolidates(tmp_path, monkeypatch) -> None:
    """With ratio=0.1, target is only 10% of budget — more rounds of archiving."""
    loop = _make_loop(tmp_path, context_window_tokens=1000, consolidation_ratio=0.1)
    loop.consolidator.archive = AsyncMock(return_value=True)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    # Interleave user/assistant so pick_consolidation_boundary can find boundaries
    session.messages = []
    for i in range(10):
        session.messages.append({"role": "user", "content": f"u{i}", "timestamp": f"2026-01-01T00:00:{i:02d}"})
        session.messages.append({"role": "assistant", "content": f"a{i}", "timestamp": f"2026-01-01T00:00:{i:02d}"})
    loop.sessions.save(session)

    # budget = 1000, target = int(1000 * 0.1) = 100
    call_count = [0]

    def mock_estimate(_session):
        call_count[0] += 1
        if call_count[0] == 1:
            return (1200, "test")
        if call_count[0] == 2:
            return (800, "test")
        if call_count[0] == 3:
            return (400, "test")
        return (50, "test")

    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    await loop.consolidator.maybe_consolidate_by_tokens(session)

    # With low ratio, more rounds needed to reach target; at least 2 rounds
    assert loop.consolidator.archive.await_count >= 2


@pytest.mark.asyncio
async def test_high_ratio_preserves_more_history(tmp_path, monkeypatch) -> None:
    """With ratio=0.9, target is 90% of budget — consolidation stops sooner."""
    loop = _make_loop(tmp_path, context_window_tokens=200, consolidation_ratio=0.9)
    loop.consolidator.archive = AsyncMock(return_value=True)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
        {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
        {"role": "assistant", "content": "a3", "timestamp": "2026-01-01T00:00:05"},
        {"role": "user", "content": "u4", "timestamp": "2026-01-01T00:00:06"},
    ]
    loop.sessions.save(session)

    # budget = 200, target = int(200 * 0.9) = 180
    call_count = [0]

    def mock_estimate(_session):
        call_count[0] += 1
        if call_count[0] == 1:
            return (300, "test")
        return (175, "test")

    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    await loop.consolidator.maybe_consolidate_by_tokens(session)

    # 300 >= 200 (triggers) → 300 > 180 → archive → 175 < 180 → stop
    assert loop.consolidator.archive.await_count == 1


@pytest.mark.asyncio
async def test_ratio_propagated_from_config_schema() -> None:
    """Verify consolidation_ratio is parsed from config with camelCase alias."""
    from nanobot.config.schema import AgentDefaults

    # Default
    defaults = AgentDefaults()
    assert defaults.consolidation_ratio == 0.5

    # camelCase alias
    defaults = AgentDefaults.model_validate({"consolidationRatio": 0.3})
    assert defaults.consolidation_ratio == 0.3

    # Serialization uses alias
    dumped = defaults.model_dump(by_alias=True)
    assert dumped["consolidationRatio"] == 0.3


@pytest.mark.asyncio
async def test_ratio_validation_rejects_out_of_range() -> None:
    """Invalid ratio values should be rejected by validation."""
    from pydantic import ValidationError
    from nanobot.config.schema import AgentDefaults

    with pytest.raises(ValidationError):
        AgentDefaults(consolidation_ratio=0.05)

    with pytest.raises(ValidationError):
        AgentDefaults(consolidation_ratio=1.0)
