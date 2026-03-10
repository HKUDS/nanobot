"""Test MemoryStore.consolidate() parses structured text responses.

Tests that memory consolidation correctly parses the ## HISTORY_ENTRY /
## MEMORY_UPDATE format returned by the LLM.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMResponse


def _make_session(message_count: int = 30):
    """Create a mock session with messages."""
    session = MagicMock()
    session.messages = [
        {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
        for i in range(message_count)
    ]
    session.last_consolidated = 0
    return session


def _make_response(history_entry: str, memory_update: str) -> LLMResponse:
    """Create an LLMResponse with the expected structured text format."""
    return LLMResponse(
        content=f"## HISTORY_ENTRY\n{history_entry}\n\n## MEMORY_UPDATE\n{memory_update}",
    )


class TestMemoryConsolidationParsing:
    """Test that consolidation parses structured text responses correctly."""

    @pytest.mark.asyncio
    async def test_valid_response_parsed(self, tmp_path: Path) -> None:
        """Normal case: LLM returns correctly formatted response."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_response(
                "[2026-01-01 00:00] User discussed testing.",
                "# Memory\nUser likes testing.",
            )
        )
        provider.chat_with_retry = provider.chat
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert store.history_file.exists()
        assert "[2026-01-01 00:00] User discussed testing." in store.history_file.read_text()
        assert "User likes testing." in store.memory_file.read_text()

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_false(self, tmp_path: Path) -> None:
        """When LLM doesn't follow the format, return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(content="I summarized the conversation.")
        )
        provider.chat_with_retry = provider.chat
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False
        assert not store.history_file.exists()

    @pytest.mark.asyncio
    async def test_empty_response_returns_false(self, tmp_path: Path) -> None:
        """Empty response should return False."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(content="")
        )
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is False

    @pytest.mark.asyncio
    async def test_skips_when_few_messages(self, tmp_path: Path) -> None:
        """Consolidation should be a no-op when messages < keep_count."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = provider.chat
        session = _make_session(message_count=10)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_unchanged_not_rewritten(self, tmp_path: Path) -> None:
        """When memory_update matches existing memory, file should not be rewritten."""
        store = MemoryStore(tmp_path)
        existing = "# Memory\nExisting facts."
        store.write_long_term(existing)

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_response(
                "[2026-01-01 00:00] Nothing new happened.",
                existing,
            )
        )
        provider.chat_with_retry = provider.chat
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert store.memory_file.read_text() == existing

    @pytest.mark.asyncio
    async def test_multiline_sections_parsed(self, tmp_path: Path) -> None:
        """Both sections can contain multiple lines."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_response(
                "[2026-01-01 00:00] First line.\nSecond line of history.",
                "# Memory\n- Fact one\n- Fact two\n- Fact three",
            )
        )
        provider.chat_with_retry = provider.chat
        session = _make_session(message_count=60)

        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert "Second line of history." in store.history_file.read_text()
        assert "Fact three" in store.memory_file.read_text()
