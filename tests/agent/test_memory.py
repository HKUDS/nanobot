"""Tests for memory system: Consolidator, token estimation, truncation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import _TIKTOKEN_ENC, Consolidator, MemoryStore, _estimate_tokens


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path)
    s.write_soul("# Soul\n- Helpful")
    s.write_user("# User\n- Developer")
    s.write_memory("# Memory\n- Project X active")
    return s


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    p.generation.max_tokens = 4096
    return p


@pytest.fixture
def mock_sessions():
    return MagicMock()


@pytest.fixture
def mock_build_messages():
    return MagicMock(return_value=[])


@pytest.fixture
def mock_get_tool_definitions():
    return MagicMock(return_value=[])


@pytest.fixture
def consolidator(store, mock_provider, mock_sessions, mock_build_messages, mock_get_tool_definitions):
    return Consolidator(
        store=store,
        provider=mock_provider,
        model="test-model",
        sessions=mock_sessions,
        context_window_tokens=128_000,
        build_messages=mock_build_messages,
        get_tool_definitions=mock_get_tool_definitions,
    )


class TestEstimateTokens:
    def test_estimate_tokens_returns_positive(self):
        assert _estimate_tokens("hello world") > 0

    def test_estimate_tokens_english_approximate(self):
        # English is roughly 1 token per 4 chars as fallback
        text = "a " * 100
        if _TIKTOKEN_ENC is not None:
            expected = len(_TIKTOKEN_ENC.encode(text))
        else:
            expected = len(text) // 4
        assert _estimate_tokens(text) == expected


class TestTruncateToTokenBudget:
    def test_reserve_tokens_reduces_budget(self, consolidator):
        long_text = "word " * 200_000
        # Without reserve, more text survives
        no_reserve = consolidator._truncate_to_token_budget(long_text, reserve_tokens=0)
        with_reserve = consolidator._truncate_to_token_budget(long_text, reserve_tokens=500)
        assert len(with_reserve) < len(no_reserve)

    def test_reserve_tokens_zero_default(self, consolidator):
        text = "hello world"
        result = consolidator._truncate_to_token_budget(text)
        assert result == text


class TestConsolidatorPrompt:
    def test_prompt_contains_snip(self):
        from nanobot.utils.prompt_templates import render_template
        text = render_template("agent/consolidator_archive.md", strip=True)
        assert "SNIP" in text
        assert "[permanent]" in text
        assert "[skip]" in text


class TestConsolidatorArchive:
    async def test_archive_injects_dedup_context(self, consolidator, mock_provider, store):
        store.write_memory("- User prefers dark mode")
        store.write_user("- Developer")
        messages = [{"role": "user", "content": "hello", "timestamp": "2026-01-01 10:00"}]

        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop"
        )
        await consolidator.archive(messages)

        call_args = mock_provider.chat_with_retry.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "## Current MEMORY.md (for dedup)" in user_msg
        assert "User prefers dark mode" in user_msg
        assert "## Current USER.md (for dedup)" in user_msg
        assert "Developer" in user_msg

    async def test_archive_skips_dedup_when_budget_exhausted(self, consolidator, mock_provider, store):
        # Shrink token budget so dedup context (always capped at ~6000 chars)
        # exceeds the available room.
        consolidator.context_window_tokens = 6_000
        store.write_memory("word " * 10_000)
        messages = [{"role": "user", "content": "hello", "timestamp": "2026-01-01 10:00"}]

        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop"
        )
        await consolidator.archive(messages)

        call_args = mock_provider.chat_with_retry.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        # Should not contain dedup context when budget is exhausted
        assert "## Current MEMORY.md (for dedup)" not in user_msg
