from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


def _make_loop(
    tmp_path,
    *,
    estimated_tokens: int,
    context_window_tokens: int,
    max_tokens: int = 0,
) -> AgentLoop:
    from nanobot.providers.base import GenerationSettings
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=max_tokens)
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
        # These tests isolate Memory consolidation; Runner request fitting is
        # covered separately with realistic context windows.
        context_block_limit=10_000,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.consolidator._SAFETY_BUFFER = 0
    return loop


@pytest.mark.asyncio
async def test_prompt_below_threshold_does_not_consolidate(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=100, context_window_tokens=200)
    loop.consolidator.archive_session = AsyncMock(return_value=True)  # type: ignore[method-assign]

    await loop.process_direct("hello", session_key="cli:test")

    loop.consolidator.archive_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_above_threshold_triggers_consolidation(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=1000, context_window_tokens=200)
    loop.consolidator.archive_session = AsyncMock(return_value=True)  # type: ignore[method-assign]
    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"{role[0]}{turn}"}
        for turn in range(10)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)

    await loop.process_direct("hello", session_key="cli:test")

    assert loop.consolidator.archive_session.await_count >= 1


@pytest.mark.asyncio
async def test_token_consolidation_refreshes_summary_for_current_request(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)
    loop.consolidator.archive_session = AsyncMock(  # type: ignore[method-assign]
        return_value="FRESH_CHECKPOINT"
    )
    loop.consolidator.estimate_session_prompt_tokens = MagicMock(  # type: ignore[method-assign]
        return_value=(1000, "test")
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"{role[0]}{turn}"}
        for turn in range(10)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)

    await loop.process_direct("hello", session_key="cli:test")

    request_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
    system_prompt = request_messages[0]["content"]
    assert "FRESH_CHECKPOINT" in system_prompt
    assert all(message.get("content") != "u0" for message in request_messages)
    assert loop.sessions.get_or_create("cli:test").last_archived == 12


@pytest.mark.asyncio
async def test_prompt_above_threshold_uses_fixed_recent_tail(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=1000, context_window_tokens=200)
    loop.consolidator.archive_session = AsyncMock(return_value=True)  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"{role[0]}{turn}"}
        for turn in range(10)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)

    await loop.consolidator.maybe_consolidate_by_tokens(
        session,
        runtime=loop.llm_runtime(),
    )

    archive_end = loop.consolidator.archive_session.await_args.kwargs["archive_end"]
    archived_chunk = session.messages[:archive_end]
    assert [message["content"] for message in archived_chunk] == [
        "u0", "a0", "u1", "a1", "u2", "a2", "u3", "a3", "u4", "a4", "u5", "a5",
    ]
    assert session.last_archived == 12


@pytest.mark.asyncio
async def test_consolidation_persists_summary_for_next_prepare_session(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)
    loop.consolidator.archive_session = AsyncMock(return_value="User discussed project status.")  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"{role[0]}{turn}"}
        for turn in range(5)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)

    def mock_estimate(_session, *, runtime):
        return (500, "test")

    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]

    await loop.consolidator.maybe_consolidate_by_tokens(
        session,
        runtime=loop.llm_runtime(),
    )

    reloaded = loop.sessions.get_or_create("cli:test")
    meta = reloaded.metadata.get("_last_summary")
    assert meta is not None
    assert meta["text"] == "User discussed project status."

    reloaded, pending = loop.auto_compact.prepare_session(reloaded, "cli:test")
    assert pending is not None
    assert pending["text"] == "User discussed project status."
    # _last_summary persists for restart survival.
    assert "_last_summary" in reloaded.metadata


@pytest.mark.asyncio
async def test_preflight_consolidation_receives_pending_summary(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=100, context_window_tokens=200)
    session = loop.sessions.get_or_create("cli:test")
    loop.auto_compact.prepare_session = MagicMock(
        return_value=(
            session,
            {"text": "earlier context", "last_active": session.updated_at.isoformat()},
        )
    )  # type: ignore[method-assign]
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=None)  # type: ignore[method-assign]
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]

    runtime = loop.llm_runtime()
    await loop.process_direct("hello", session_key="cli:test", runtime=runtime)

    loop.consolidator.maybe_consolidate_by_tokens.assert_any_await(
        session,
        runtime=runtime,
    )
    assert len(loop.consolidator.maybe_consolidate_by_tokens.call_args_list) == 2
    assert all(
        call.kwargs["runtime"] is runtime
        for call in loop.consolidator.maybe_consolidate_by_tokens.call_args_list
    )


@pytest.mark.asyncio
async def test_preflight_consolidation_before_llm_call(tmp_path) -> None:
    """Verify preflight consolidation runs before the LLM call in process_direct."""
    order: list[str] = []

    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)

    archived_session_keys: list[str | None] = []

    async def track_consolidate(session, *, archive_end, runtime):
        order.append("consolidate")
        archived_session_keys.append(session.key)
        return True
    loop.consolidator.archive_session = track_consolidate  # type: ignore[method-assign]

    async def track_llm(*args, **kwargs):
        order.append("llm")
        return LLMResponse(content="ok", tool_calls=[])
    loop.provider.chat_with_retry = track_llm
    loop.provider.chat_stream_with_retry = track_llm
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"{role[0]}{turn}"}
        for turn in range(10)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)
    call_count = [0]
    def mock_estimate(_session, *, runtime):
        call_count[0] += 1
        return (1000 if call_count[0] <= 1 else 80, "test")
    loop.consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]

    await loop.process_direct("hello", session_key="cli:test")

    assert "consolidate" in order
    assert "llm" in order
    assert order.index("consolidate") < order.index("llm")
    assert archived_session_keys == ["cli:test"]
