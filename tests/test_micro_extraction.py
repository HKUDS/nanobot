"""Tests for micro-extraction (per-turn memory extraction)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.memory.write.micro_extractor import _MICRO_EXTRACT_TOOL, MicroExtractor


def test_config_defaults():
    """Micro-extraction config fields exist with correct defaults."""
    from nanobot.config.agent import AgentConfig

    config = AgentConfig()
    assert config.memory.micro_extraction_enabled is False
    assert config.memory.micro_extraction_model is None


def test_tool_schema_has_required_fields():
    """Tool schema requires events array."""
    schema = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]
    assert "events" in schema["properties"]
    assert "events" in schema["required"]


def test_tool_schema_event_types():
    """Event type enum has all 6 valid types."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    expected = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    assert set(items["properties"]["type"]["enum"]) == expected


def test_tool_schema_event_required_fields():
    """Each event requires type and summary."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    assert set(items["required"]) == {"type", "summary"}


def _make_tool_response(events: list[dict]) -> MagicMock:
    """Create a mock LLM response with a save_events tool call."""
    tc = MagicMock()
    tc.name = "save_events"
    tc.arguments = {"events": events}
    resp = MagicMock()
    resp.tool_calls = [tc]
    resp.content = None
    return resp


def _make_text_response(text: str) -> MagicMock:
    """Create a mock LLM response with no tool calls."""
    resp = MagicMock()
    resp.tool_calls = []
    resp.content = text
    return resp


class TestMicroExtractor:
    """Tests for MicroExtractor."""

    def setup_method(self):
        self.provider = AsyncMock()
        self.ingester = MagicMock()
        self.ingester.append_events = MagicMock(return_value=2)

    def _make_extractor(self, *, enabled: bool = True) -> MicroExtractor:
        return MicroExtractor(
            provider=self.provider,
            ingester=self.ingester,
            model="test-model",
            enabled=enabled,
        )

    @pytest.mark.asyncio
    async def test_submit_when_disabled_does_nothing(self):
        ext = self._make_extractor(enabled=False)
        await ext.submit("hello", "hi there")
        await asyncio.sleep(0.05)
        self.provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_extracts_and_ingests_events(self):
        events = [
            {"type": "fact", "summary": "User works on DS10540"},
            {"type": "relationship", "summary": "Alice is the project lead"},
        ]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()
        await ext.submit("I work on DS10540 with Alice", "Got it!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert len(written) == 2
        assert written[0].summary == "User works on DS10540"

    @pytest.mark.asyncio
    async def test_submit_empty_events_skips_ingestion(self):
        self.provider.chat = AsyncMock(return_value=_make_tool_response([]))
        ext = self._make_extractor()
        await ext.submit("ok thanks", "You're welcome!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_no_tool_call_skips_ingestion(self):
        self.provider.chat = AsyncMock(return_value=_make_text_response("Nothing to save."))
        ext = self._make_extractor()
        await ext.submit("ok thanks", "You're welcome!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_is_nonblocking(self):
        """submit() returns immediately without waiting for extraction."""

        async def slow_chat(**kwargs):
            await asyncio.sleep(10)
            return _make_tool_response([])

        self.provider.chat = slow_chat
        ext = self._make_extractor()
        await ext.submit("test", "test")
        assert len(ext._pending_tasks) == 1

    @pytest.mark.asyncio
    async def test_submit_failure_logs_warning(self):
        self.provider.chat = AsyncMock(side_effect=RuntimeError("API down"))
        ext = self._make_extractor()
        await ext.submit("test", "test")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_ingestion_failure_logs_warning(self):
        self.provider.chat = AsyncMock(
            return_value=_make_tool_response([{"type": "fact", "summary": "test"}])
        )
        self.ingester.append_events = MagicMock(side_effect=RuntimeError("DB error"))
        ext = self._make_extractor()
        await ext.submit("test", "test")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_parses_string_arguments(self):
        """LLM may return tool arguments as a JSON string instead of dict."""
        events = [{"type": "fact", "summary": "User likes Python"}]
        tc = MagicMock()
        tc.name = "save_events"
        tc.arguments = json.dumps({"events": events})
        resp = MagicMock()
        resp.tool_calls = [tc]
        resp.content = None
        self.provider.chat = AsyncMock(return_value=resp)
        ext = self._make_extractor()
        await ext.submit("I like Python", "Noted!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert written[0].summary == "User likes Python"


@pytest.mark.usefixtures("propagate_loguru_to_caplog")
@pytest.mark.asyncio
async def test_empty_parse_logs_debug(caplog: pytest.LogCaptureFixture) -> None:
    """When _parse_events returns empty, a debug message is logged."""
    mock_provider = AsyncMock()
    mock_provider.chat.return_value = MagicMock(tool_calls=None)
    mock_ingester = MagicMock()

    extractor = MicroExtractor(
        provider=mock_provider,
        ingester=mock_ingester,
        model="gpt-4o-mini",
        enabled=True,
    )

    with caplog.at_level(logging.DEBUG, logger="nanobot.memory.write.micro_extractor"):
        await extractor._extract_and_ingest(
            "user msg", "assistant msg", channel="", tool_hints=[], turn_timestamp=""
        )

    assert any("no events parsed" in r.message.lower() for r in caplog.records)
    mock_ingester.append_events.assert_not_called()
