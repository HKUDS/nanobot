from unittest.mock import AsyncMock, MagicMock

import pytest

import nanobot.agent.memory as memory_module
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse


def _make_loop(tmp_path, *, estimated_tokens: int, context_window_tokens: int) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100) # Small generation budget
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
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.memory_consolidator._SAFETY_BUFFER = 0
    return loop

@pytest.mark.asyncio
async def test_consolidation_falls_back_on_token_estimation_failure(tmp_path, monkeypatch) -> None:
    # Fix for Issue 2
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=20000)
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)

    session = loop.sessions.get_or_create("cli:test")
    # Add enough messages to trigger heuristic fallback (needs > 50)
    session.messages = [{"role": "user", "content": "u", "timestamp": "2026-01-01T00:00:00"}] * 100
    loop.sessions.save(session)

    # Mock estimate_session_prompt_tokens to return 0 (simulating tiktoken failure)
    loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(0, "none"))

    # Mock boundary picking since estimate is 0 (we manually set it to 100*200 in the code)
    # boundary should be found.

    await loop.memory_consolidator.maybe_consolidate_by_tokens(session)

    # Should have triggered consolidation using heuristic
    assert loop.memory_consolidator.consolidate_messages.await_count >= 1
    assert session.last_consolidated > 0

@pytest.mark.asyncio
async def test_hard_budget_enforcement_works(tmp_path, monkeypatch) -> None:
    # Fix for Issue 1
    # context window 5000, generation budget 100, safety 1024. Hard cap is ~3876.
    loop = _make_loop(tmp_path, estimated_tokens=5000, context_window_tokens=5000)

    # Mock consolidation to always fail (forcing hard budget enforcement)
    loop.memory_consolidator.maybe_consolidate_by_tokens = AsyncMock()

    session = loop.sessions.get_or_create("cli:test")
    # Add many messages
    session.messages = [
        {"role": "user", "content": f"u{i}", "timestamp": "2026-01-01T00:00:00"}
        for i in range(100)
    ]
    loop.sessions.save(session)

    # Mock estimate_session_prompt_tokens to return 5000
    loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(5000, "test"))

    # Mock message token estimation
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    from nanobot.bus.events import InboundMessage
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hi")

    # This should trigger _enforce_session_budget and advance last_consolidated
    await loop._process_message(msg, session_key="cli:test")

    assert session.last_consolidated > 0

    # Check if HISTORY.md got the raw dump
    history_file = tmp_path / "memory" / "HISTORY.md"
    assert history_file.exists()
    assert "[RAW]" in history_file.read_text()

@pytest.mark.asyncio
async def test_memory_context_truncation(tmp_path) -> None:
    # Fix for Issue 4
    from nanobot.agent.context import ContextBuilder
    builder = ContextBuilder(tmp_path)

    large_memory = "X" * 20000
    builder.memory.write_long_term(large_memory)

    prompt = builder.build_system_prompt()
    assert "Memory" in prompt
    assert "...(truncated. Full content in memory/MEMORY.md)" in prompt
    # Baseline prompt is ~5K, memory truncated to 16K.
    assert len(prompt) < 25000
