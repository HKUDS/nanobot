from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import (
    GenerationSettings,
    LLMResponse,
    ProviderConversationState,
)
from nanobot.session.summary import SUMMARY_CONTINUATION_TEXT


def _make_loop(
    tmp_path,
    *,
    estimated_tokens: int,
    context_window_tokens: int,
    max_tokens: int = 0,
) -> AgentLoop:
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
    session = loop.sessions.get_or_create("cli:test")
    session.add_message("user", "hello")

    await loop.consolidator.maybe_consolidate_by_tokens(
        session,
        runtime=loop.llm_runtime(),
    )

    loop.consolidator.archive_session.assert_not_awaited()


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
async def test_runner_pressure_commits_summary_and_current_delta(tmp_path) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=100, context_window_tokens=2_000)
    loop.context_block_limit = 500
    loop.provider.generation = GenerationSettings(max_tokens=100)
    loop.provider.can_resume_conversation_state.return_value = False
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": role, "content": f"old-{role}-{turn}"}
        for turn in range(6)
        for role in ("user", "assistant")
    ]
    loop.sessions.save(session)

    def estimate(messages, _tools, _model):
        contents = [str(message.get("content")) for message in messages]
        if contents and "SNIP" in contents[-1]:
            return 300, "test-counter"
        if any(content.startswith("old-") for content in contents):
            return 600, "test-counter"
        return 100, "test-counter"

    loop.provider.estimate_prompt_tokens.side_effect = estimate
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="Current checkpoint.", tool_calls=[]),
        LLMResponse(content="done", tool_calls=[]),
    ])

    result = await loop.process_direct("continue the task", session_key="cli:test")

    assert result.content == "done"
    assert loop.provider.chat_with_retry.await_count == 2
    model_request = loop.provider.chat_with_retry.await_args_list[1].kwargs["messages"]
    assert "Current checkpoint." in model_request[0]["content"]
    assert model_request[1]["content"] == SUMMARY_CONTINUATION_TEXT
    assert model_request[2]["content"] == "continue the task"

    reloaded = loop.sessions.get_or_create("cli:test")
    assert reloaded.messages[0]["content"] == "old-user-0"
    assert reloaded.metadata["_last_summary"]["text"] == "Current checkpoint."
    assert reloaded.messages[reloaded.last_archived]["content"] == (
        SUMMARY_CONTINUATION_TEXT
    )
    assert [message["content"] for message in reloaded.get_history()] == [
        SUMMARY_CONTINUATION_TEXT,
        "continue the task",
        "done",
    ]


@pytest.mark.asyncio
async def test_native_provider_compaction_commits_portable_terminal_checkpoint(
    tmp_path,
) -> None:
    loop = _make_loop(tmp_path, estimated_tokens=100, context_window_tokens=2_000)
    session = loop.sessions.get_or_create("cli:native")
    session.messages = [
        {"role": "user", "content": "accepted history"},
        {"role": "assistant", "content": "accepted answer"},
    ]
    loop.sessions.save(session)
    compacted_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": [{"type": "compaction", "encrypted_content": "opaque"}]},
    )
    loop.provider.can_resume_conversation_state.return_value = True
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="done",
        provider_state=compacted_state,
        provider_compaction_applied=True,
    ))
    loop.consolidator.summarize_transcript = AsyncMock(
        return_value="portable terminal checkpoint",
    )

    result = await loop.process_direct("continue", session_key="cli:native")

    assert result.content == "done"
    summarize = loop.consolidator.summarize_transcript
    summarize.assert_awaited_once()
    accepted = summarize.await_args.args[0]
    accepted_contents = [message.get("content") for message in accepted]
    assert "accepted history" in accepted_contents
    assert "accepted answer" in accepted_contents
    assert "continue" not in accepted_contents
    assert "done" not in accepted_contents
    reloaded = loop.sessions.get_or_create("cli:native")
    assert reloaded.provider_state is None
    assert reloaded.metadata["_last_summary"]["text"] == (
        "portable terminal checkpoint"
    )
    assert reloaded.messages[reloaded.last_archived]["content"] == (
        SUMMARY_CONTINUATION_TEXT
    )
    assert [message["content"] for message in reloaded.get_history()] == [
        SUMMARY_CONTINUATION_TEXT,
        "continue",
        "done",
    ]
