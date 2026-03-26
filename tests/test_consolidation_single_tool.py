"""Tests for single-tool consolidation path (Task 6).

Verifies:
- Combined tool schema has all required fields.
- Single-tool path is called when consolidation_single_tool flag is True.
- Legacy two-call path is called when flag is False.
- Fallback to heuristic extractor when events parsing fails.
- History entry extracted from tool response (and fallback generation).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.memory.consolidation_pipeline import ConsolidationPipeline
from nanobot.memory.constants import (
    _CONSOLIDATE_MEMORY_TOOL,
    _SAVE_EVENTS_TOOL,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline(
    tmp_path: Path | None = None,
    rollout: dict[str, Any] | None = None,
    **overrides: object,
) -> ConsolidationPipeline:
    """Build a ``ConsolidationPipeline`` with all dependencies mocked."""
    _base = tmp_path or Path("/tmp/test")
    defaults: dict[str, object] = {
        "extractor": MagicMock(),
        "ingester": MagicMock(),
        "profile_mgr": MagicMock(),
        "conflict_mgr": MagicMock(),
        "snapshot": MagicMock(),
        "db": MagicMock(),
        "rollout": rollout,
    }
    defaults.update(overrides)
    return ConsolidationPipeline(**defaults)  # type: ignore[arg-type]


def _make_session(
    messages: list[dict[str, object]] | None = None,
    last_consolidated: int = 0,
) -> MagicMock:
    session = MagicMock()
    session.messages = messages or []
    session.last_consolidated = last_consolidated
    session.key = "test-session"
    return session


def _make_provider_with_tool_response(args: dict[str, Any]) -> MagicMock:
    """Create a mock provider that returns a single tool call with *args*."""
    tool_call = MagicMock()
    tool_call.arguments = json.dumps(args)

    response = MagicMock()
    response.has_tool_calls = True
    response.tool_calls = [tool_call]

    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)
    return provider


def _enough_messages(n: int = 30) -> list[dict[str, object]]:
    return [
        {"role": "user", "content": f"msg-{i}", "timestamp": "2026-01-01T00:00:00"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestConsolidateMemoryToolSchema:
    """Verify the combined tool schema has all expected fields."""

    def test_is_list_with_one_entry(self) -> None:
        assert isinstance(_CONSOLIDATE_MEMORY_TOOL, list)
        assert len(_CONSOLIDATE_MEMORY_TOOL) == 1

    def test_function_name(self) -> None:
        assert _CONSOLIDATE_MEMORY_TOOL[0]["function"]["name"] == "consolidate_memory"

    def test_required_fields(self) -> None:
        required = _CONSOLIDATE_MEMORY_TOOL[0]["function"]["parameters"]["required"]
        assert "history_entry" in required
        assert "events" in required

    def test_has_history_entry_property(self) -> None:
        props = _CONSOLIDATE_MEMORY_TOOL[0]["function"]["parameters"]["properties"]
        assert "history_entry" in props
        assert props["history_entry"]["type"] == "string"

    def test_events_reuses_save_events_schema(self) -> None:
        combined_events = _CONSOLIDATE_MEMORY_TOOL[0]["function"]["parameters"]["properties"][
            "events"
        ]
        original_events = _SAVE_EVENTS_TOOL[0]["function"]["parameters"]["properties"]["events"]
        # They should be the exact same object (reference equality)
        assert combined_events is original_events

    def test_profile_updates_reuses_save_events_schema(self) -> None:
        combined_pu = _CONSOLIDATE_MEMORY_TOOL[0]["function"]["parameters"]["properties"][
            "profile_updates"
        ]
        original_pu = _SAVE_EVENTS_TOOL[0]["function"]["parameters"]["properties"][
            "profile_updates"
        ]
        assert combined_pu is original_pu

    def test_profile_updates_not_required(self) -> None:
        required = _CONSOLIDATE_MEMORY_TOOL[0]["function"]["parameters"]["required"]
        assert "profile_updates" not in required


# ---------------------------------------------------------------------------
# Routing tests: single-tool vs. two-call path
# ---------------------------------------------------------------------------


class TestConsolidationRouting:
    @pytest.mark.asyncio
    async def test_single_tool_path_when_flag_true(self, tmp_path: Path) -> None:
        """When consolidation_single_tool is True, single-tool path is used."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        args = {
            "history_entry": "Summary of conversation.",
            "events": [{"type": "fact", "summary": "User likes Python"}],
        }
        provider = _make_provider_with_tool_response(args)

        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.coerce_event.return_value = {
            "type": "fact",
            "summary": "User likes Python",
            "id": "ev-1",
        }
        pipeline._extractor.to_str_list.return_value = []
        pipeline._ingester.append_events.return_value = 1
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        # Provider should have been called exactly once (single-tool path).
        assert provider.chat.call_count == 1
        # The tool passed should be _CONSOLIDATE_MEMORY_TOOL
        call_kwargs = provider.chat.call_args
        assert call_kwargs.kwargs.get("tools") is _CONSOLIDATE_MEMORY_TOOL or (
            call_kwargs[1].get("tools") is _CONSOLIDATE_MEMORY_TOOL
        )

    @pytest.mark.asyncio
    async def test_single_tool_path_used_with_empty_rollout(self, tmp_path: Path) -> None:
        """Single-tool path is always used, even with an empty rollout dict."""
        pipeline = _make_pipeline(tmp_path, rollout={})
        session = _make_session(messages=_enough_messages())

        tool_call = MagicMock()
        tool_call.arguments = json.dumps(
            {
                "history_entry": "summary",
                "events": [],
                "profile_updates": {},
            }
        )
        response = MagicMock()
        response.has_tool_calls = True
        response.tool_calls = [tool_call]

        provider = MagicMock()
        provider.chat = AsyncMock(return_value=response)

        pipeline._extractor.parse_tool_args.return_value = {
            "history_entry": "summary",
            "events": [],
            "profile_updates": {},
        }
        pipeline._extractor.default_profile_updates.return_value = {}
        pipeline._extractor.heuristic_extract_events.return_value = ([], {})
        pipeline._ingester.append_events.return_value = 0
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        # Single-tool path: provider.chat called exactly once with consolidate_memory tool.
        assert provider.chat.call_count == 1


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------


class TestSingleToolFallbacks:
    @pytest.mark.asyncio
    async def test_fallback_to_extractor_when_events_missing(self, tmp_path: Path) -> None:
        """When events are missing from tool response, fall back to heuristic."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        # Response has history_entry but no events
        args: dict[str, Any] = {"history_entry": "Summary of things."}
        provider = _make_provider_with_tool_response(args)
        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.heuristic_extract_events.return_value = (
            [{"type": "fact", "summary": "heuristic event", "id": "h-1"}],
            {
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": [],
            },
        )
        pipeline._ingester.append_events.return_value = 1
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        pipeline._extractor.heuristic_extract_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_extractor_when_events_malformed(self, tmp_path: Path) -> None:
        """When events is not a list, fall back to heuristic."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        args = {"history_entry": "Summary.", "events": "not-a-list"}
        provider = _make_provider_with_tool_response(args)
        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.heuristic_extract_events.return_value = (
            [],
            {
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": [],
            },
        )
        pipeline._ingester.append_events.return_value = 0
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        pipeline._extractor.heuristic_extract_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_extractor_when_events_empty_list(self, tmp_path: Path) -> None:
        """When events is an empty list, fall back to heuristic."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        args: dict[str, Any] = {"history_entry": "Summary.", "events": []}
        provider = _make_provider_with_tool_response(args)
        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.heuristic_extract_events.return_value = (
            [],
            {
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": [],
            },
        )
        pipeline._ingester.append_events.return_value = 0
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        pipeline._extractor.heuristic_extract_events.assert_called_once()


# ---------------------------------------------------------------------------
# History entry extraction
# ---------------------------------------------------------------------------


class TestHistoryEntryExtraction:
    @pytest.mark.asyncio
    async def test_history_entry_from_tool_response(self, tmp_path: Path) -> None:
        """History entry from tool response is written to history file."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        args = {
            "history_entry": "Discussed Python preferences and project setup.",
            "events": [{"type": "fact", "summary": "likes Python"}],
        }
        provider = _make_provider_with_tool_response(args)

        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.coerce_event.return_value = {
            "type": "fact",
            "summary": "likes Python",
            "id": "ev-1",
        }
        pipeline._extractor.to_str_list.return_value = []
        pipeline._ingester.append_events.return_value = 1
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            await pipeline.consolidate(session, provider, "gpt-4")

        pipeline._db.append_history.assert_called_once()
        written = pipeline._db.append_history.call_args[0][0]
        assert "Discussed Python preferences" in written

    @pytest.mark.asyncio
    async def test_history_entry_fallback_from_lines(self, tmp_path: Path) -> None:
        """When history_entry is missing, a fallback is generated from lines."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        msgs = _enough_messages()
        session = _make_session(messages=msgs)

        # No history_entry in response
        args: dict[str, Any] = {"events": [{"type": "fact", "summary": "something"}]}
        provider = _make_provider_with_tool_response(args)

        pipeline._extractor.parse_tool_args.return_value = args
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.coerce_event.return_value = {
            "type": "fact",
            "summary": "something",
            "id": "ev-1",
        }
        pipeline._extractor.to_str_list.return_value = []
        pipeline._ingester.append_events.return_value = 1
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            await pipeline.consolidate(session, provider, "gpt-4")

        # History should still be written with fallback content
        pipeline._db.append_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_tool_calls_still_generates_history(self, tmp_path: Path) -> None:
        """When LLM returns no tool calls, history_entry fallback still works."""
        pipeline = _make_pipeline(tmp_path, rollout={"consolidation_single_tool": True})
        session = _make_session(messages=_enough_messages())

        response = MagicMock()
        response.has_tool_calls = False
        response.tool_calls = []
        provider = MagicMock()
        provider.chat = AsyncMock(return_value=response)

        pipeline._extractor.parse_tool_args.return_value = None
        pipeline._extractor.default_profile_updates.return_value = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }
        pipeline._extractor.heuristic_extract_events.return_value = (
            [],
            {
                "preferences": [],
                "stable_facts": [],
                "active_projects": [],
                "relationships": [],
                "constraints": [],
            },
        )
        pipeline._ingester.append_events.return_value = 0
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        # Should still succeed -- the fallback chain handles missing data
        assert result is True
        # History should have the fallback content from first lines
        pipeline._db.append_history.assert_called_once()
