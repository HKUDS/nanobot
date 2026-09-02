"""Tests for Memory checkpoint consolidation and history journaling."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import (
    _HISTORY_ENTRY_HARD_CAP,
    Consolidator,
    MemoryStore,
)
from nanobot.providers.base import (
    GenerationSettings,
    LLMResponse,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    RuntimeContextBlock,
    append_runtime_context,
)
from nanobot.session.keys import UNIFIED_SESSION_KEY, remember_last_channel
from nanobot.session.manager import Session
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

_ARCHIVE_PROMPT = render_template("agent/consolidator_archive.md", strip=True)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    p.generation = GenerationSettings(max_tokens=100)
    return p


@pytest.fixture
def runtime(mock_provider):
    return LLMRuntime.capture(
        mock_provider,
        "test-model",
        context_window_tokens=1000,
    )


@pytest.fixture
def consolidator(store):
    sessions = MagicMock()
    sessions.save = MagicMock()
    # Store sessions by key so refreshes observe the same test object.
    _session_cache: dict[str, MagicMock] = {}
    sessions.get_or_create = MagicMock(side_effect=lambda key: _session_cache.get(key, MagicMock()))
    sessions._session_cache = _session_cache
    return Consolidator(
        store=store,
        sessions=sessions,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
    )


def _tool_round(call_id: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "x", "content": "ok"},
    ]


def _provider_state() -> ProviderConversationState:
    return ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": []},
    )


def _build_test_messages(**kwargs):
    system = "system prompt"
    session_summary = kwargs.get("session_summary")
    if session_summary:
        system += f"\n\n[Archived Context Summary]\n{session_summary['text']}"
    messages = [
        {"role": "system", "content": system},
        *kwargs["history"],
    ]
    if kwargs["current_message"] is not None:
        messages.append({"role": "user", "content": kwargs["current_message"]})
    return messages


async def _archive(
    consolidator,
    messages,
    runtime,
    *,
    session_key="test:session",
    previous_summary=None,
):
    return await consolidator.archiver.archive(
        messages,
        runtime=runtime,
        session_key=session_key,
        history=[
            {"role": "system", "content": "system prompt"},
            *messages,
        ],
        request_tools=[],
        previous_summary=previous_summary,
    )


class TestTurnTranscriptSummary:
    async def test_uses_exact_accepted_prefix_and_existing_archiver(
        self,
        consolidator,
        mock_provider,
        runtime,
    ):
        accepted = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": "accepted history"},
        ]
        tools = [{"type": "function", "function": {"name": "inspect"}}]
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content="replacement checkpoint",
        )

        summary = await consolidator.summarize_transcript(
            accepted,
            "previous checkpoint",
            runtime=runtime,
            session_key="test:turn",
            tools=tools,
        )

        assert summary == "replacement checkpoint"
        call = mock_provider.chat_with_retry.await_args.kwargs
        assert call["messages"][:-1] == accepted
        assert call["messages"][-1]["role"] == "user"
        assert "SNIP" in call["messages"][-1]["content"]
        assert call["tools"] == tools

    async def test_native_compaction_appends_only_archive_prompt(
        self,
        consolidator,
        mock_provider,
        runtime,
    ):
        accepted = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": "raw history must not be replayed"},
        ]
        state = _provider_state()
        mock_provider.can_resume_conversation_state.return_value = True
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content="replacement checkpoint",
        )

        summary = await consolidator.summarize_provider_compaction(
            state,
            accepted,
            "previous checkpoint",
            runtime=runtime,
            session_key="test:turn",
            tools=[{"type": "function", "function": {"name": "inspect"}}],
        )

        assert summary == "replacement checkpoint"
        call = mock_provider.chat_with_retry.await_args.kwargs
        assert call["messages"][0] == accepted[0]
        assert call["messages"][-1]["content"] == _ARCHIVE_PROMPT
        assert accepted[1] not in call["messages"]
        assert call["tools"] == []
        provider_context = call["provider_context"]
        assert provider_context.conversation_state is not None
        assert provider_context.conversation_state.payload == state.payload
        assert provider_context.conversation_state.pending_messages == [
            call["messages"][-1],
        ]


class TestConsolidatorSummarize:
    def test_format_messages_keeps_media_only_user_turn(self):
        path = "/home/user/.nanobot/media/websocket/clip.mp4"

        formatted = MemoryStore._format_messages([
            {
                "role": "user",
                "content": "",
                "media": [path],
                "timestamp": "2026-07-27",
            }
        ])

        assert formatted == f"[2026-07-27] USER: [image: {path}]"

    async def test_archive_uses_captured_generation(
        self, consolidator, mock_provider, runtime
    ):
        admitted = replace(
            runtime,
            generation=GenerationSettings(
                temperature=0.25,
                max_tokens=321,
                reasoning_effort="medium",
            ),
        )
        mock_provider.generation = GenerationSettings(
            temperature=0.9,
            max_tokens=999,
            reasoning_effort="high",
        )
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.",
            finish_reason="stop",
        )

        await _archive(consolidator, [{"role": "user", "content": "hello"}], admitted)

        call = mock_provider.chat_with_retry.call_args.kwargs
        assert call["model"] == admitted.model
        assert call["temperature"] == 0.25
        assert call["max_tokens"] == 321
        assert call["reasoning_effort"] == "medium"

    async def test_summarize_appends_to_history(
        self, consolidator, mock_provider, store, runtime
    ):
        """Consolidator should call LLM to summarize, then append to HISTORY.md."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module."
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await _archive(consolidator, messages, runtime)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1

    async def test_summarize_appends_session_key_to_history(
        self,
        consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [{"role": "user", "content": "fix the auth bug"}]

        await _archive(
            consolidator,
            messages,
            runtime,
            session_key="telegram:chat-1",
        )

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "telegram:chat-1"

    async def test_summarize_raw_dumps_on_llm_failure(
        self, consolidator, mock_provider, store, runtime
    ):
        """On LLM failure, raw-dump messages to HISTORY.md."""
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]
        result = await _archive(consolidator, messages, runtime)
        assert result is not None
        assert "[RAW]" in result
        assert "hello" in result
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]

    async def test_raw_dump_fallback_appends_session_key(
        self,
        consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]

        await _archive(
            consolidator,
            messages,
            runtime,
            session_key="slack:chat-2",
        )

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "slack:chat-2"

    async def test_raw_fallback_represents_previous_checkpoint_and_new_chunk(
        self,
        consolidator,
        mock_provider,
        runtime,
    ):
        runtime = replace(runtime, generation=GenerationSettings(max_tokens=96))
        mock_provider.chat_with_retry.side_effect = RuntimeError("API error")

        result = await _archive(
            consolidator,
            [{"role": "user", "content": "NEW_MARKER " + "new " * 200}],
            runtime,
            previous_summary="OLD_MARKER " + "old " * 200,
        )

        assert result is not None
        assert "[Previous archived context]" in result
        assert "OLD_MARKER" in result
        assert "[Newly archived raw context]" in result
        assert "NEW_MARKER" in result
        assert "... (truncated)" in result

    async def test_summarize_skips_empty_messages(self, consolidator, runtime):
        result = await _archive(consolidator, [], runtime)
        assert result is None


class TestConsolidatorPromptContract:
    def test_archive_prompt_requests_a_cumulative_replacement_checkpoint(self):
        prompt = _ARCHIVE_PROMPT

        for section in ("## Merge rules", "## What to retain", "## Output"):
            assert section in prompt
        assert "replacement checkpoint" in prompt
        assert "[Archived Context Summary]" in prompt
        assert "current conversation state" in prompt
        assert "SNIP" in prompt
        for mark in ("[permanent]", "[durable]", "[ephemeral]", "[correction]"):
            assert mark in prompt
        assert "working-state handoff" in prompt
        assert "- [mark] fact" in prompt
        assert "[skip]" not in prompt
        assert "(nothing)" in prompt
        assert "history.jsonl" not in prompt


class TestConsolidatorArchiveErrorHandling:
    """archive() must fall back when the LLM does not complete its overview.

    Error responses include overloaded / quota failures from #3244; length
    responses contain a partial overview that is likewise unsafe to persist.
    """

    @pytest.mark.parametrize("finish_reason", ["error", "length"])
    async def test_archive_falls_back_on_incomplete_finish_reason(
        self,
        consolidator,
        mock_provider,
        store,
        runtime,
        finish_reason: str,
    ):
        """Incomplete LLM output should trigger raw_archive, not persist partial text."""
        invalid_output = f"INVALID_{finish_reason.upper()}_OUTPUT"
        mock_provider.chat_with_retry.return_value = MagicMock(
            content=invalid_output,
            finish_reason=finish_reason,
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await _archive(consolidator, messages, runtime)
        assert result is not None
        assert "[RAW]" in result
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]
        assert invalid_output not in entries[0]["content"]

    async def test_archive_preserves_summary_on_success(
        self, consolidator, mock_provider, store, runtime
    ):
        """Normal LLM response should still produce a proper summary entry."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done."},
        ]
        result = await _archive(consolidator, messages, runtime)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" not in entries[0]["content"]

    async def test_archive_propagates_history_write_failure(
        self, consolidator, mock_provider, runtime
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.",
            finish_reason="stop",
        )
        consolidator.store.append_history = MagicMock(side_effect=OSError("disk full"))
        consolidator.store.raw_archive = MagicMock()

        with pytest.raises(OSError, match="disk full"):
            await _archive(
                consolidator,
                [{"role": "user", "content": "important"}],
                runtime,
            )

        consolidator.store.raw_archive.assert_not_called()

    async def test_archive_propagates_template_failure_without_raw_archive(
        self, consolidator, mock_provider, runtime, monkeypatch
    ):
        runtime = replace(runtime, context_window_tokens=128_000)
        consolidator.store.raw_archive = MagicMock()
        monkeypatch.setattr(
            "nanobot.agent.memory.render_template",
            MagicMock(side_effect=RuntimeError("template failed")),
        )
        session = Session(key="test:template")
        session.add_message("user", "important")

        with pytest.raises(RuntimeError, match="template failed"):
            await consolidator.archive_session(
                session,
                archive_end=len(session.messages),
                runtime=runtime,
            )

        mock_provider.chat_with_retry.assert_not_awaited()
        consolidator.store.raw_archive.assert_not_called()


class TestConsolidatorPromptEstimate:
    async def test_estimate_uses_full_unarchived_tail(self, consolidator, runtime):
        """Consolidation pressure must account for the full unarchived tail."""
        session = Session(key="test:full-tail")
        for i in range(160):
            session.add_message("user", f"msg-{i}")

        captured: dict[str, list[dict]] = {}

        def build_messages(**kwargs):
            captured["history"] = kwargs["history"]
            return kwargs["history"]

        consolidator._build_messages = build_messages

        consolidator.estimate_session_prompt_tokens(session, runtime=runtime)

        assert len(captured["history"]) == 160
        assert captured["history"][0]["content"].endswith("msg-0")

    async def test_estimate_includes_recent_archived_replay(self, consolidator, runtime):
        session = Session(key="test:archived-replay")
        for i in range(10):
            session.add_message("user", f"msg-{i}")
        session.last_archived = len(session.messages)

        captured: dict[str, list[dict]] = {}

        def build_messages(**kwargs):
            captured["history"] = kwargs["history"]
            return kwargs["history"]

        consolidator._build_messages = build_messages

        consolidator.estimate_session_prompt_tokens(session, runtime=runtime)

        assert len(captured["history"]) == 8
        assert captured["history"][0]["content"] == "msg-2"

class TestCompactIdleSession:
    """Idle compaction tests."""

    @pytest.fixture
    def runtime(self, mock_provider):
        """Exercise the structured idle-consolidation path by default."""
        return LLMRuntime.capture(
            mock_provider,
            "test-model",
            context_window_tokens=128_000,
        )

    @pytest.fixture
    def real_consolidator(self, store, mock_provider):
        """Create a Consolidator with a real SessionManager (not a mock)."""
        from nanobot.session.manager import SessionManager

        sessions = SessionManager(store.workspace)
        return Consolidator(
            store=store,
            sessions=sessions,
            build_messages=MagicMock(side_effect=_build_test_messages),
            get_tool_definitions=MagicMock(return_value=[]),
        )

    @pytest.mark.asyncio
    async def test_archives_full_tail_preserves_messages_and_replays_recent_suffix(
        self, real_consolidator, mock_provider, runtime
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:test")
        session.provider_state = _provider_state()
        old_ts = session.updated_at
        for i in range(20):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        session.updated_at = old_ts
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:test", runtime=runtime, max_suffix=8
        )
        assert result == "Summary of old conversation."

        sessions.invalidate("cli:test")
        reloaded = sessions.get_or_create("cli:test")
        assert len(reloaded.messages) == 40
        assert reloaded.messages[0]["content"] == "user msg 0"
        assert reloaded.last_archived == 40
        assert reloaded.provider_state == _provider_state()
        visible = reloaded.get_history(max_messages=40)
        assert len(visible) == 8
        assert visible[0]["content"] == "user msg 16"
        assert visible[-1]["content"] == "assistant msg 19"
        meta = reloaded.metadata.get("_last_summary")
        assert meta is not None
        assert meta["text"] == "Summary of old conversation."
        assert "last_active" in meta
        assert reloaded.updated_at == old_ts

    @pytest.mark.asyncio
    async def test_short_idle_session_archives_once(
        self, real_consolidator, mock_provider, store, runtime
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Short summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:short")
        session.add_message("user", "hello")
        session.add_message("assistant", "hi")
        sessions.save(session)

        first = await real_consolidator.compact_idle_session("cli:short", runtime=runtime)
        second = await real_consolidator.compact_idle_session("cli:short", runtime=runtime)

        assert first == "Short summary."
        assert second == ""
        mock_provider.chat_with_retry.assert_awaited_once()
        assert len(store.read_unprocessed_history(since_cursor=0)) == 1
        reloaded = sessions.get_or_create("cli:short")
        assert reloaded.last_archived == 2
        assert [message["content"] for message in reloaded.get_history()] == ["hello", "hi"]

    @pytest.mark.asyncio
    async def test_idle_compaction_with_no_new_messages_is_noop(
        self, real_consolidator, mock_provider, store, runtime
    ):
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:archived-idle")
        session.add_message("user", "already archived")
        session.add_message("assistant", "old answer")
        session.last_archived = 2
        sessions.save(session)
        sessions.invalidate("cli:archived-idle")

        result = await real_consolidator.compact_idle_session(
            "cli:archived-idle",
            runtime=runtime,
        )

        assert result == ""
        mock_provider.chat_with_retry.assert_not_awaited()
        reloaded = sessions.get_or_create("cli:archived-idle")
        assert reloaded.last_archived == 2
        assert "_last_summary" not in reloaded.metadata
        assert store.read_unprocessed_history(since_cursor=0) == []

    @pytest.mark.asyncio
    async def test_new_messages_advance_existing_archive_progress(
        self, real_consolidator, mock_provider, runtime
    ):
        mock_provider.chat_with_retry.side_effect = [
            MagicMock(content="First replacement checkpoint.", finish_reason="stop"),
            MagicMock(content="Second replacement checkpoint.", finish_reason="stop"),
        ]
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:incremental")
        session.add_message("user", "first user")
        session.add_message("assistant", "first assistant")
        sessions.save(session)

        first = await real_consolidator.compact_idle_session(
            "cli:incremental",
            runtime=runtime,
        )
        current = sessions.get_or_create("cli:incremental")
        current.add_message("user", "second user")
        current.add_message("assistant", "second assistant")
        sessions.save(current)
        second = await real_consolidator.compact_idle_session(
            "cli:incremental",
            runtime=runtime,
        )

        assert first == "First replacement checkpoint."
        assert second == "Second replacement checkpoint."
        assert mock_provider.chat_with_retry.await_count == 2
        latest_build = real_consolidator.archiver._build_messages.call_args_list[-1].kwargs
        assert latest_build["session_summary"]["text"] == "First replacement checkpoint."
        latest_messages = mock_provider.chat_with_retry.await_args_list[-1].kwargs["messages"]
        assert [message["content"] for message in latest_messages[1:5]] == [
            "first user",
            "first assistant",
            "second user",
            "second assistant",
        ]
        assert latest_messages[-1]["content"] == _ARCHIVE_PROMPT
        sessions.invalidate("cli:incremental")
        reloaded = sessions.get_or_create("cli:incremental")
        assert reloaded.last_archived == 4
        assert reloaded.metadata["_last_summary"]["text"] == second

    @pytest.mark.asyncio
    async def test_raw_fallback_preserves_previous_checkpoint_and_new_chunk(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.side_effect = [
            LLMResponse(content="Earlier durable checkpoint.", finish_reason="stop"),
            RuntimeError("LLM unavailable"),
        ]
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:cumulative-fallback")
        session.add_message("user", "first user")
        session.add_message("assistant", "first answer")
        sessions.save(session)

        await real_consolidator.compact_idle_session(
            "cli:cumulative-fallback",
            runtime=runtime,
        )
        current = sessions.get_or_create("cli:cumulative-fallback")
        current.add_message("user", "second user")
        current.add_message("assistant", "newest working state")
        sessions.save(current)

        fallback = await real_consolidator.compact_idle_session(
            "cli:cumulative-fallback",
            runtime=runtime,
        )

        assert fallback is not None
        assert "[Previous archived context]" in fallback
        assert "Earlier durable checkpoint." in fallback
        assert "[Newly archived raw context]" in fallback
        assert "newest working state" in fallback
        entries = store.read_unprocessed_history(0)
        assert entries[0]["content"] == "Earlier durable checkpoint."
        assert entries[1]["content"].startswith("[RAW] 2 messages")
        sessions.invalidate("cli:cumulative-fallback")
        reloaded = sessions.get_or_create("cli:cumulative-fallback")
        assert reloaded.metadata["_last_summary"]["text"] == fallback

    @pytest.mark.asyncio
    async def test_nothing_keeps_previous_replacement_checkpoint(
        self,
        real_consolidator,
        mock_provider,
        runtime,
    ):
        mock_provider.chat_with_retry.side_effect = [
            LLMResponse(content="Existing checkpoint.", finish_reason="stop"),
            LLMResponse(content="(nothing)", finish_reason="stop"),
        ]
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:nothing-after-summary")
        session.add_message("user", "important first turn")
        session.add_message("assistant", "important result")
        sessions.save(session)
        await real_consolidator.compact_idle_session(
            "cli:nothing-after-summary",
            runtime=runtime,
        )

        current = sessions.get_or_create("cli:nothing-after-summary")
        current.add_message("user", "thanks")
        current.add_message("assistant", "you're welcome")
        sessions.save(current)
        result = await real_consolidator.compact_idle_session(
            "cli:nothing-after-summary",
            runtime=runtime,
        )

        assert result == "(nothing)"
        sessions.invalidate("cli:nothing-after-summary")
        reloaded = sessions.get_or_create("cli:nothing-after-summary")
        assert reloaded.last_archived == 4
        assert reloaded.metadata["_last_summary"]["text"] == "Existing checkpoint."

    @pytest.mark.asyncio
    async def test_concurrent_append_remains_unarchived(
        self, real_consolidator, mock_provider, runtime
    ):
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:concurrent")
        session.add_message("user", "captured user")
        session.add_message("assistant", "captured assistant")
        sessions.save(session)

        async def append_during_archive(**_kwargs):
            current = sessions.get_or_create("cli:concurrent")
            current.add_message("user", "late user")
            current.add_message("assistant", "late assistant")
            return LLMResponse(content="Summary.", finish_reason="stop")

        mock_provider.chat_with_retry.side_effect = append_during_archive

        await real_consolidator.compact_idle_session("cli:concurrent", runtime=runtime)

        reloaded = sessions.get_or_create("cli:concurrent")
        assert len(reloaded.messages) == 4
        assert reloaded.last_archived == 2

    @pytest.mark.asyncio
    async def test_summarizes_retained_suffix_not_just_dropped_prefix(
        self, real_consolidator, mock_provider, runtime
    ):
        """idleCompact must summarize over the full unarchived tail, including
        the recent suffix it retains. Otherwise a late user correction / final
        result that lands in the kept suffix is excluded from the persisted
        summary, leaving a stale wrong conclusion in history. Regression for #4264."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:correction")
        for i in range(18):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        # Final correction exchange lands inside the retained max_suffix window.
        session.add_message("user", "no, that's wrong, use approach B")
        session.add_message("assistant", "CORRECTED_FINAL_RESULT_alpha")
        sessions.save(session)

        await real_consolidator.compact_idle_session(
            "cli:correction", runtime=runtime, max_suffix=8
        )

        sent_messages = mock_provider.chat_with_retry.call_args.kwargs["messages"]
        assert any(
            message.get("content") == "CORRECTED_FINAL_RESULT_alpha"
            for message in sent_messages
        )

    @pytest.mark.asyncio
    async def test_raw_dumps_full_archive_batch_on_llm_failure(
        self, real_consolidator, mock_provider, store, runtime
    ):
        """The fallback covers the same full range as successful idle archival."""
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:rawdrop")
        session.provider_state = _provider_state()
        for i in range(18):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        session.add_message("user", "final user follow-up")
        session.add_message("assistant", "RETAINED_SUFFIX_marker")
        sessions.save(session)

        await real_consolidator.compact_idle_session(
            "cli:rawdrop", runtime=runtime, max_suffix=8
        )

        raw = "\n".join(e["content"] for e in store.read_unprocessed_history(since_cursor=0))
        assert "[RAW]" in raw
        assert "user msg 0" in raw
        assert "RETAINED_SUFFIX_marker" in raw
        reloaded = sessions.get_or_create("cli:rawdrop")
        assert len(reloaded.messages) == 38
        assert reloaded.messages[-1]["content"] == "RETAINED_SUFFIX_marker"
        assert reloaded.provider_state == _provider_state()

    @pytest.mark.asyncio
    async def test_idle_compact_writes_session_key_to_history(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        session = real_consolidator.sessions.get_or_create("cli:test")
        for i in range(10):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        real_consolidator.sessions.save(session)

        await real_consolidator.compact_idle_session(
            "cli:test", runtime=runtime, max_suffix=4
        )

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "cli:test"

    @pytest.mark.asyncio
    async def test_empty_session_does_not_refresh_timestamp(
        self, real_consolidator, runtime
    ):
        """Empty session with old updated_at does not look active after compaction."""
        from datetime import datetime, timedelta

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:empty")
        old_ts = datetime.now() - timedelta(hours=2)
        session.updated_at = old_ts
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:empty", runtime=runtime
        )
        assert result == ""

        reloaded = sessions.get_or_create("cli:empty")
        assert reloaded.updated_at == old_ts
        assert reloaded.metadata == {}

    @pytest.mark.asyncio
    async def test_nothing_summary_not_stored(
        self, real_consolidator, mock_provider, runtime
    ):
        """LLM returns '(nothing)' → neither history nor metadata stores it."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:nothing")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:nothing", runtime=runtime, max_suffix=4
        )
        second = await real_consolidator.compact_idle_session(
            "cli:nothing", runtime=runtime, max_suffix=4
        )
        assert result == "(nothing)"
        assert second == ""

        reloaded = sessions.get_or_create("cli:nothing")
        assert "_last_summary" not in reloaded.metadata
        assert real_consolidator.store.read_unprocessed_history(0) == []
        mock_provider.chat_with_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_preserves_history_but_advances_replay_boundary(
        self, real_consolidator, mock_provider, store, runtime
    ):
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:fail")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:fail", runtime=runtime, max_suffix=4
        )
        assert result is not None
        assert "[RAW]" in result

        # raw_archive should have been called (history.jsonl gets an entry)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert any("[RAW]" in e["content"] for e in entries)

        reloaded = sessions.get_or_create("cli:fail")
        assert len(reloaded.messages) == 20
        assert reloaded.messages[0]["content"] == "u0"
        assert reloaded.last_archived == 20
        assert reloaded.metadata["_last_summary"]["text"] == result
        assert [m["content"] for m in reloaded.get_history(max_messages=20)] == [
            "u6",
            "a6",
            "u7",
            "a7",
            "u8",
            "a8",
            "u9",
            "a9",
        ]

    @pytest.mark.asyncio
    async def test_respects_last_archived(
        self, real_consolidator, mock_provider, runtime
    ):
        """30 turns with last_archived=50 → only the unarchived tail is considered."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:offset")
        for i in range(30):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        session.last_archived = 50  # Only 10 messages remain unarchived
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:offset", runtime=runtime, max_suffix=4
        )
        assert result == "Tail summary."
        reloaded = sessions.get_or_create("cli:offset")
        assert len(reloaded.messages) == 60
        assert reloaded.last_archived == 60

        # Verify only the unarchived tail was processed:
        # All 10 unarchived messages (50-59) are archived exactly once.
        archived_call = mock_provider.chat_with_retry.call_args
        sent_messages = archived_call.kwargs["messages"]
        sent_content = [message.get("content") for message in sent_messages]
        # The replacement overview covers all model-visible conversation context.
        assert "u0" not in sent_content
        assert "u26" in sent_content
        assert sent_messages[-1]["content"] == _ARCHIVE_PROMPT

    @pytest.mark.asyncio
    async def test_full_archive_keeps_extended_legal_replay_suffix(
        self,
        real_consolidator,
        mock_provider,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:noncontiguous")
        for i in range(15):
            session.add_message("user", f"user-{i:02d}")
        for i in range(10):
            session.add_message("assistant", f"assistant-{i:02d}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:noncontiguous", runtime=runtime, max_suffix=6
        )
        assert result == "Tail summary."

        reloaded = sessions.get_or_create("cli:noncontiguous")
        assert len(reloaded.messages) == 25
        assert reloaded.last_archived == 25
        assert [m["content"] for m in reloaded.get_history(max_messages=25)] == [
            "user-14",
            "assistant-00",
            "assistant-01",
            "assistant-02",
            "assistant-03",
            "assistant-04",
            "assistant-05",
            "assistant-06",
            "assistant-07",
            "assistant-08",
            "assistant-09",
        ]

        # #4264: idle compaction now summarizes the full unarchived tail, so
        # the dropped head (user-00) and retained suffix (user-14 through
        # assistant-09) are all summarized.
        archived_call = mock_provider.chat_with_retry.call_args
        sent_content = [message.get("content") for message in archived_call.kwargs["messages"]]
        assert "user-00" in sent_content
        assert "assistant-09" in sent_content
        assert "user-14" in sent_content

    @pytest.mark.asyncio
    async def test_preserves_tool_history_and_persists_only_overview(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        tools = [{"type": "function", "function": {"name": "lookup"}}]
        real_consolidator.archiver._get_tool_definitions.return_value = tools
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content="Overview from the temporary turn.",
            finish_reason="stop",
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:tool-history")
        session.add_message("user", "look this up")
        session.messages.extend(_tool_round("call-1"))
        session.add_message("assistant", "final answer")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:tool-history",
            runtime=runtime,
        )

        assert result == "Overview from the temporary turn."
        call = mock_provider.chat_with_retry.call_args.kwargs
        sent_messages = call["messages"]
        assert [message["role"] for message in sent_messages] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "user",
        ]
        assert sent_messages[2]["tool_calls"][0]["id"] == "call-1"
        assert sent_messages[-1]["content"] == _ARCHIVE_PROMPT
        assert call["tools"] == tools
        assert "tool_choice" not in call

        reloaded = sessions.get_or_create("cli:tool-history")
        assert len(reloaded.messages) == 4
        assert reloaded.messages[-1]["content"] == "final answer"
        assert all(
            "memory overview" not in str(message.get("content", "")).lower()
            for message in reloaded.messages
        )
        entries = store.read_unprocessed_history(since_cursor=0)
        assert [entry["content"] for entry in entries] == [
            "Overview from the temporary turn."
        ]

    @pytest.mark.asyncio
    async def test_tool_call_response_uses_raw_fallback(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call-1", name="lookup", arguments={})],
            finish_reason="tool_calls",
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:unexpected-tool")
        session.add_message("user", "remember this")
        session.add_message("assistant", "important answer")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:unexpected-tool",
            runtime=runtime,
        )

        assert result is not None
        assert "[RAW]" in result
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["content"].startswith("[RAW] ")
        assert "important answer" in entries[0]["content"]
        assert sessions.get_or_create("cli:unexpected-tool").last_archived == 2

    @pytest.mark.asyncio
    async def test_empty_response_uses_raw_fallback(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content="",
            finish_reason="stop",
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:empty-summary")
        session.add_message("user", "remember this")
        session.add_message("assistant", "important answer")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "cli:empty-summary",
            runtime=runtime,
        )

        assert result is not None
        assert "[RAW]" in result
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["content"].startswith("[RAW] ")
        assert "important answer" in entries[0]["content"]
        assert sessions.get_or_create("cli:empty-summary").last_archived == 2

    @pytest.mark.asyncio
    async def test_oversized_prefix_raw_archives_without_flattened_llm_retry(
        self,
        real_consolidator,
        mock_provider,
        store,
        runtime,
    ):
        runtime = replace(runtime, context_window_tokens=1_000)
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("sdk:oversized")
        session.add_message("user", "x" * 100_000)
        sessions.save(session)

        result = await real_consolidator.compact_idle_session(
            "sdk:oversized",
            runtime=runtime,
        )

        assert result is not None
        assert "[RAW]" in result
        mock_provider.chat_with_retry.assert_not_awaited()
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["content"].startswith("[RAW] ")
        assert sessions.get_or_create("sdk:oversized").last_archived == 1

    @pytest.mark.asyncio
    async def test_archive_context_contains_only_model_visible_messages(
        self,
        real_consolidator,
        mock_provider,
        runtime,
    ):
        mock_provider.chat_with_retry.return_value = LLMResponse(
            content="Summary.",
            finish_reason="stop",
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:commands")
        session.add_message("user", "already archived user")
        session.add_message("assistant", "already archived answer")
        session.last_archived = 2
        session.add_message("user", "/status", _command=True)
        session.add_message("assistant", "status output", _command=True)
        session.add_message("user", "new user")
        session.add_message("assistant", "new answer")
        sessions.save(session)

        await real_consolidator.compact_idle_session(
            "cli:commands",
            runtime=runtime,
        )

        sent = mock_provider.chat_with_retry.call_args.kwargs["messages"]
        assert [message.get("content") for message in sent[1:-1]] == [
            "already archived user",
            "already archived answer",
            "new user",
            "new answer",
        ]
        assert sent[-1]["content"] == _ARCHIVE_PROMPT

    @pytest.mark.asyncio
    async def test_reuses_real_prefix_for_unified_session_workspace(
        self,
        loop_factory,
        mock_provider,
        tmp_path,
    ):
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "AGENTS.md").write_text("GLOBAL_WORKSPACE_MARKER", encoding="utf-8")
        (project / "AGENTS.md").write_text("PROJECT_WORKSPACE_MARKER", encoding="utf-8")
        loop = loop_factory(provider=mock_provider, unified_session=True)
        runtime = loop.llm_runtime()
        runtime.provider.chat_with_retry.return_value = LLMResponse(
            content="Summary.",
            finish_reason="stop",
        )
        session = loop.sessions.get_or_create(UNIFIED_SESSION_KEY)
        remember_last_channel(session.metadata, "websocket", "scope")
        session.metadata["workspace_scope"] = {
            "project_path": str(project),
            "access_mode": "restricted",
        }
        session.add_message("user", "project question")
        session.add_message("assistant", "project answer")
        loop.sessions.save(session)
        ordinary_messages = loop.context.build_messages(
            history=session.get_history(max_messages=0),
            current_message="next project question",
            channel="websocket",
            workspace=project,
        )

        await loop.consolidator.compact_idle_session(
            session.key,
            runtime=runtime,
        )

        sent_messages = runtime.provider.chat_with_retry.call_args.kwargs["messages"]
        assert sent_messages[:-1] == ordinary_messages[:-1]
        assert sent_messages[-1]["content"] == _ARCHIVE_PROMPT
        system = sent_messages[0]["content"]
        assert "PROJECT_WORKSPACE_MARKER" in system
        assert "GLOBAL_WORKSPACE_MARKER" not in system

    @pytest.mark.asyncio
    async def test_acquires_consolidation_lock(
        self, real_consolidator, mock_provider, runtime
    ):
        """Verify lock is held during execution."""
        import asyncio

        # Use a slow LLM response to ensure the lock is held while we check
        started = asyncio.Event()
        release_chat = asyncio.Event()

        async def slow_chat(**kwargs):
            started.set()
            await release_chat.wait()
            return LLMResponse(content="Summary.", finish_reason="stop")

        mock_provider.chat_with_retry = slow_chat

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:lock")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        lock = real_consolidator.get_lock("cli:lock")
        assert not lock.locked()

        task = asyncio.ensure_future(
            real_consolidator.compact_idle_session(
                "cli:lock", runtime=runtime, max_suffix=4
            )
        )
        await started.wait()
        assert lock.locked()
        release_chat.set()
        await task
        assert not lock.locked()


class TestRawArchiveTruncation:
    """raw_archive() must cap entry size to avoid bloating history.jsonl."""

    def test_raw_archive_truncates_large_content(self, store):
        """Large messages should be truncated to _RAW_ARCHIVE_MAX_CHARS."""
        big = "x" * 50_000
        messages = [{"role": "user", "content": big}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert len(entries[0]["content"]) < 50_000
        assert "[RAW]" in entries[0]["content"]

    def test_raw_archive_preserves_small_content(self, store):
        """Small messages should not be truncated."""
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "hello" in entries[0]["content"]

    def test_raw_archive_returns_the_sanitized_persisted_checkpoint(self, store):
        messages = [
            {
                "role": "user",
                "content": "<think>PRIVATE_REASONING</think>visible result",
            }
        ]

        checkpoint = store.raw_archive(messages, session_key="cli:test")

        persisted = store.read_unprocessed_history(since_cursor=0)[0]["content"]
        assert checkpoint == persisted
        assert "PRIVATE_REASONING" not in checkpoint
        assert "visible result" in checkpoint

    def test_raw_archive_excludes_model_only_runtime_context(self, store):
        content, marker = append_runtime_context(
            "ship the feature",
            [RuntimeContextBlock(source="goal", content="host-only goal guidance")],
        )

        store.raw_archive([{
            "role": "user",
            "content": content,
            RUNTIME_CONTEXT_HISTORY_META: marker,
        }])

        entry = store.read_unprocessed_history(since_cursor=0)[0]["content"]
        assert "ship the feature" in entry
        assert "host-only goal guidance" not in entry

    def test_raw_archive_preserves_session_key(self, store):
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages, session_key="websocket:chat-1")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "websocket:chat-1"

    def test_raw_archive_custom_max_chars(self, store):
        """max_chars parameter should override default limit."""
        messages = [{"role": "user", "content": "a" * 200}]
        store.raw_archive(messages, max_chars=100)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries[0]["content"]) < 200


class TestArchivePersistence:
    async def test_archive_returns_the_sanitized_persisted_summary(
        self, consolidator, mock_provider, store, runtime
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="<think>PRIVATE_REASONING</think>safe summary",
            finish_reason="stop",
            has_tool_calls=False,
        )

        summary = await _archive(
            consolidator,
            [{"role": "user", "content": "hi"}],
            runtime,
        )

        persisted = store.read_unprocessed_history(since_cursor=0)[0]["content"]
        assert summary == persisted == "safe summary"

    async def test_oversized_summary_uses_history_emergency_cap(
        self, consolidator, mock_provider, store, runtime
    ):
        """A pathologically large LLM summary must not land full-length in
        history.jsonl — that would re-open the #3412 bloat vector from the
        *success* path instead of the fallback path."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="S" * (_HISTORY_ENTRY_HARD_CAP * 2),
            finish_reason="stop",
        )
        summary = await _archive(
            consolidator,
            [{"role": "user", "content": "hi"}],
            runtime,
        )

        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert len(entry["content"]) <= _HISTORY_ENTRY_HARD_CAP + 50
        assert summary == entry["content"]
