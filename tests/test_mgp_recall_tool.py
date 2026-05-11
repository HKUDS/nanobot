"""Tests for nanobot.agent.tools.mgp_recall.MGPRecallTool.

We mock the sidecar entirely (the sidecar itself is exercised in
``test_mgp_sidecar.py``) so these tests focus on:

- JSON Schema validation (required ``query``, enum / bound enforcement)
- default scope/limit fall-throughs
- ContextVar plumbing of channel/chat_id/effective_key
- ``_format`` rendering for empty / normal / degraded outcomes
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.mgp.models import RecallOutcome, RecallItem
from nanobot.agent.tools.mgp_recall import MGPRecallTool


def _runtime_stub() -> SimpleNamespace:
    """A trivial RuntimeState stand-in; the tool only forwards it."""
    return SimpleNamespace(channel="cli", chat_id="alice", user_id="alice")


@pytest.fixture
def mock_sidecar() -> MagicMock:
    sc = MagicMock()
    sc.build_runtime = MagicMock(return_value=_runtime_stub())
    sc.recall = AsyncMock(return_value=RecallOutcome(executed=True, degraded=False, results=[]))
    return sc


@pytest.fixture
def tool(mock_sidecar: MagicMock) -> MGPRecallTool:
    return MGPRecallTool(sidecar=mock_sidecar, default_scope="user", default_limit=5)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_schema_marks_query_required(self, tool: MGPRecallTool) -> None:
        params = tool.parameters
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "query" in params["required"]

    def test_validate_missing_query_fails(self, tool: MGPRecallTool) -> None:
        errors = tool.validate_params({})
        assert errors, "missing query should produce an error"

    def test_validate_with_only_query_passes(self, tool: MGPRecallTool) -> None:
        assert tool.validate_params({"query": "indentation preference"}) == []

    def test_validate_scope_enum_enforced(self, tool: MGPRecallTool) -> None:
        ok = tool.validate_params({"query": "x", "scope": "user"})
        assert ok == []
        bad = tool.validate_params({"query": "x", "scope": "WORLD"})
        assert bad, "non-enum scope should fail validation"

    def test_validate_limit_bounds_enforced(self, tool: MGPRecallTool) -> None:
        assert tool.validate_params({"query": "x", "limit": 1}) == []
        assert tool.validate_params({"query": "x", "limit": 20}) == []
        assert tool.validate_params({"query": "x", "limit": 0})
        assert tool.validate_params({"query": "x", "limit": 21})

    def test_to_schema_includes_function_name(self, tool: MGPRecallTool) -> None:
        schema = tool.to_schema()
        assert schema["function"]["name"] == "recall_memory"
        assert schema["function"]["description"]
        # read_only flag flows through (used by concurrency planning).
        assert tool.read_only is True


# ---------------------------------------------------------------------------
# execute → defaults
# ---------------------------------------------------------------------------


class TestExecuteDefaults:
    @pytest.mark.asyncio
    async def test_uses_default_scope_and_limit(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        await tool.execute(query="indentation preference")
        assert mock_sidecar.recall.await_count == 1
        intent = mock_sidecar.recall.await_args.args[1]
        assert intent.scope == "user"
        assert intent.limit == 5
        assert intent.types is None

    @pytest.mark.asyncio
    async def test_per_call_overrides_take_precedence(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        await tool.execute(query="x", scope="agent", limit=12, types=["preference"])
        intent = mock_sidecar.recall.await_args.args[1]
        assert intent.scope == "agent"
        assert intent.limit == 12
        assert intent.types == ["preference"]


# ---------------------------------------------------------------------------
# set_context → ContextVar plumbing
# ---------------------------------------------------------------------------


class TestSetContext:
    @pytest.mark.asyncio
    async def test_set_context_threads_runtime_via_contextvar(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        tool.set_context("telegram", "u-99", effective_key="telegram:u-99")
        await tool.execute(query="topic")
        kwargs = mock_sidecar.build_runtime.call_args.kwargs
        assert kwargs == {
            "channel": "telegram",
            "chat_id": "u-99",
            "session_key": "telegram:u-99",
            "sender_id": None,
        }

    @pytest.mark.asyncio
    async def test_set_context_synthesizes_session_key_when_missing(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        tool.set_context("cli", "direct")
        await tool.execute(query="x")
        kwargs = mock_sidecar.build_runtime.call_args.kwargs
        assert kwargs["session_key"] == "cli:direct"

    @pytest.mark.asyncio
    async def test_set_context_handles_none_safely(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        tool.set_context(None, None)
        await tool.execute(query="x")
        kwargs = mock_sidecar.build_runtime.call_args.kwargs
        assert kwargs == {
            "channel": None,
            "chat_id": None,
            "session_key": None,
            "sender_id": None,
        }

    @pytest.mark.asyncio
    async def test_set_context_propagates_sender_id_for_group_chats(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        # Regression: in group chats, every member shares one ``chat_id``.
        # Without per-member ``sender_id`` plumbing the sidecar would
        # collapse all of them into the same MGP subject. The tool MUST
        # forward sender_id so user-scoped recall works correctly.
        tool.set_context(
            "telegram", "group-77", effective_key="telegram:group-77", sender_id="alice",
        )
        await tool.execute(query="topic")
        kwargs = mock_sidecar.build_runtime.call_args.kwargs
        assert kwargs["sender_id"] == "alice"
        assert kwargs["chat_id"] == "group-77"


# ---------------------------------------------------------------------------
# _format
# ---------------------------------------------------------------------------


class TestFormat:
    def test_format_empty_results(self) -> None:
        out = MGPRecallTool._format(RecallOutcome(executed=True, degraded=False, results=[]))
        assert out == "(no memories found)"

    def test_format_normal_results(self) -> None:
        results = [
            RecallItem(
                memory={"type": "preference"},
                consumable_text="User prefers dark mode.",
            ),
            RecallItem(
                memory={"type": "semantic_fact"},
                consumable_text="Project Atlas uses pgvector.",
            ),
        ]
        out = MGPRecallTool._format(RecallOutcome(executed=True, degraded=False, results=results))
        lines = out.splitlines()
        assert lines == [
            "- [preference] User prefers dark mode.",
            "- [semantic_fact] Project Atlas uses pgvector.",
        ]

    def test_format_falls_back_to_content_dict(self) -> None:
        # When consumable_text is absent we should still render something useful.
        item = RecallItem(
            memory={"type": "preference", "content": {"statement": "Dark mode."}},
            consumable_text=None,
        )
        out = MGPRecallTool._format(RecallOutcome(executed=True, degraded=False, results=[item]))
        assert out == "- [preference] Dark mode."

    def test_format_degraded_outcome(self) -> None:
        outcome = RecallOutcome(
            executed=False, degraded=True,
            error_code="ConnectError", error_message="refused",
        )
        out = MGPRecallTool._format(outcome)
        assert "degraded" in out
        assert "ConnectError" in out

    @pytest.mark.asyncio
    async def test_execute_returns_format_output(
        self,
        tool: MGPRecallTool,
        mock_sidecar: MagicMock,
    ) -> None:
        mock_sidecar.recall.return_value = RecallOutcome(
            executed=True, degraded=False,
            results=[RecallItem(memory={"type": "preference"}, consumable_text="A.")],
        )
        out = await tool.execute(query="x")
        assert out == "- [preference] A."
