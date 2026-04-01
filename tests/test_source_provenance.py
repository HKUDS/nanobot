"""Tests for source provenance on memory events."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.turn_types import ToolAttempt
from nanobot.memory.read.retrieval_types import RetrievalScores, RetrievedMemory
from nanobot.memory.write.micro_extractor import MicroExtractor, _build_source


def _make_attempt(tool_name: str, arguments: dict | None = None) -> ToolAttempt:
    """Helper to build a ToolAttempt with sensible defaults."""
    return ToolAttempt(
        tool_name=tool_name,
        arguments=arguments or {},
        success=True,
        output_empty=False,
        output_snippet="some output",
        iteration=1,
    )


class TestExtractToolHints:
    """Tests for _extract_tool_hints in message_processor."""

    def test_non_exec_tool_uses_name_directly(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("read_file", {"path": "/foo/bar.md"})]
        assert _extract_tool_hints(attempts) == ["read_file"]

    def test_exec_with_command_extracts_first_word(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": "obsidian search query=DS10540"})]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_exec_without_command_arg_returns_exec(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"working_dir": "/tmp"})]
        assert _extract_tool_hints(attempts) == ["exec"]

    def test_deduplicates_identical_hints(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian search query=DS10540"}),
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("exec", {"command": "obsidian search query=other"}),
        ]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_mixed_tools_sorted_and_deduped(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("read_file", {"path": "/foo/bar.md"}),
            _make_attempt("exec", {"command": "obsidian search query=test"}),
            _make_attempt("list_dir", {"path": "/foo"}),
        ]
        result = _extract_tool_hints(attempts)
        assert result == sorted(result)  # return value is already in sorted order
        assert set(result) == {"exec:obsidian", "list_dir", "read_file"}

    def test_empty_attempts_returns_empty(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        assert _extract_tool_hints([]) == []

    def test_exec_with_empty_command_string(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": ""})]
        assert _extract_tool_hints(attempts) == ["exec"]

    def test_exec_with_non_string_command(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": None, "timeout": 60})]
        assert _extract_tool_hints(attempts) == ["exec"]


class TestBuildSource:
    """Tests for _build_source in micro_extractor."""

    def test_channel_only_no_tools(self):
        assert _build_source("cli", []) == "cli"

    def test_channel_with_tools(self):
        assert _build_source("cli", ["exec:obsidian", "read_file"]) == "cli,exec:obsidian,read_file"

    def test_empty_channel_defaults_to_unknown(self):
        assert _build_source("", ["read_file"]) == "unknown,read_file"

    def test_tools_are_sorted(self):
        result = _build_source("web", ["read_file", "exec:git", "exec:obsidian"])
        assert result == "web,exec:git,exec:obsidian,read_file"

    def test_duplicate_tools_deduped(self):
        result = _build_source("cli", ["exec:obsidian", "exec:obsidian", "read_file"])
        assert result == "cli,exec:obsidian,read_file"


def _make_tool_response(events: list[dict]) -> MagicMock:
    """Create a mock LLM response with a save_events tool call."""
    tc = MagicMock()
    tc.name = "save_events"
    tc.arguments = {"events": events}
    resp = MagicMock()
    resp.tool_calls = [tc]
    resp.content = None
    return resp


class TestMicroExtractorProvenance:
    """Tests that MicroExtractor stamps provenance on events."""

    def setup_method(self):
        self.provider = AsyncMock()
        self.ingester = MagicMock()
        self.ingester.append_events = MagicMock(return_value=1)

    def _make_extractor(self) -> MicroExtractor:
        return MicroExtractor(
            provider=self.provider,
            ingester=self.ingester,
            model="test-model",
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_submit_stamps_source_on_events(self):
        events = [{"type": "fact", "summary": "DS10540 duration is 186 days"}]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()

        await ext.submit(
            "summarize DS10540",
            "Duration is 186 days",
            channel="cli",
            tool_hints=["exec:obsidian", "read_file"],
            turn_timestamp="2026-03-31T14:30:00",
        )
        await asyncio.sleep(0.1)

        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert len(written) == 1
        assert written[0].source == "cli,exec:obsidian,read_file"
        assert written[0].metadata.get("source_timestamp") == "2026-03-31T14:30:00"

    @pytest.mark.asyncio
    async def test_submit_without_provenance_uses_defaults(self):
        """Backward compat: calling submit() without provenance params still works."""
        events = [{"type": "fact", "summary": "test fact"}]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()

        await ext.submit("hello", "hi")
        await asyncio.sleep(0.1)

        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert written[0].source == "chat"  # default, unchanged


class TestMemoryItemLineProvenance:
    """Tests for provenance rendering in context_assembler._memory_item_line."""

    @staticmethod
    def _make_item(
        source: str = "",
        summary: str = "DS10540 planned duration is 186 days",
        event_type: str = "fact",
        timestamp: str = "2026-03-25T14:30:00",
        provider: str = "vector",
    ) -> RetrievedMemory:
        return RetrievedMemory(
            id="test-1",
            type=event_type,
            summary=summary,
            timestamp=timestamp,
            source=source,
            scores=RetrievalScores(semantic=0.85, recency=0.72, provider=provider),
        )

    def test_with_provenance_includes_from(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli,exec:obsidian,read_file")
        line = ContextAssembler._memory_item_line(item)
        assert "from: cli,exec:obsidian,read_file" in line
        assert "(fact, from: cli,exec:obsidian,read_file)" in line

    def test_legacy_chat_source_no_provenance_label(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="chat")
        line = ContextAssembler._memory_item_line(item)
        assert "from:" not in line
        assert "(fact)" in line

    def test_empty_source_no_provenance_label(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="")
        line = ContextAssembler._memory_item_line(item)
        assert "from:" not in line

    def test_no_retrieval_method_in_output(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli", provider="vector")
        line = ContextAssembler._memory_item_line(item)
        assert "src=" not in line
        assert "src=vector" not in line

    def test_scores_still_present(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli")
        line = ContextAssembler._memory_item_line(item)
        assert "sem=0.85" in line
        assert "rec=0.72" in line
