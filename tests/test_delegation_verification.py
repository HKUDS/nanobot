"""Tests for Phase D — delegation result verification.

Covers:
- ``DelegationResult`` dataclass and ``grounded`` property
- ``DelegateTool._format_result`` attestation markers
- ``_INVESTIGATION_RE`` detection
- ``Scratchpad`` metadata and ``_grounded_tag``
- ``DelegateParallelTool`` grounded/ungrounded tags
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.coordination.scratchpad import Scratchpad
from nanobot.tools.builtin.delegate import (
    _INVESTIGATION_RE,
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
)

# ---------------------------------------------------------------------------
# DelegationResult
# ---------------------------------------------------------------------------


class TestDelegationResult:
    def test_grounded_when_tools_used(self) -> None:
        dr = DelegationResult(content="found it", tools_used=["read_file", "exec"])
        assert dr.grounded is True

    def test_not_grounded_when_no_tools(self) -> None:
        dr = DelegationResult(content="I think so", tools_used=[])
        assert dr.grounded is False

    def test_single_tool_is_grounded(self) -> None:
        dr = DelegationResult(content="data", tools_used=["web_search"])
        assert dr.grounded is True


# ---------------------------------------------------------------------------
# _INVESTIGATION_RE
# ---------------------------------------------------------------------------


class TestInvestigationRegex:
    @pytest.mark.parametrize(
        "task",
        [
            "search for the latest report",
            "find the user's email",
            "look up pricing info",
            "check if the server is running",
            "verify the claim about X",
            "investigate the bug",
            "retrieve the document",
            "fetch the API response",
            "query the database",
            "inspect the logs",
        ],
    )
    def test_matches_investigation_tasks(self, task: str) -> None:
        assert _INVESTIGATION_RE.search(task) is not None

    @pytest.mark.parametrize(
        "task",
        [
            "write a summary",
            "format the report",
            "translate this text",
            "create a plan",
        ],
    )
    def test_does_not_match_non_investigation(self, task: str) -> None:
        assert _INVESTIGATION_RE.search(task) is None


# ---------------------------------------------------------------------------
# DelegateTool._format_result
# ---------------------------------------------------------------------------


class TestFormatResult:
    def test_grounded_result_includes_marker(self) -> None:
        dr = DelegationResult(content="answer", tools_used=["exec", "read_file"])
        result = DelegateTool._format_result(dr, "write code")
        assert result.success
        assert "[tools_used=2, grounded=True]" in result.output
        assert "answer" in result.output

    def test_ungrounded_non_investigation_no_warning(self) -> None:
        dr = DelegationResult(content="answer", tools_used=[])
        result = DelegateTool._format_result(dr, "summarize this")
        assert result.success
        assert "[tools_used=0, grounded=False]" in result.output
        assert "⚠️" not in result.output

    def test_ungrounded_investigation_has_warning(self) -> None:
        dr = DelegationResult(content="answer", tools_used=[])
        result = DelegateTool._format_result(dr, "search for the user's email")
        assert result.success
        assert "[tools_used=0, grounded=False]" in result.output
        assert "⚠️" in result.output
        assert "not be verified" in result.output


# ---------------------------------------------------------------------------
# DelegateTool.execute with DelegationResult
# ---------------------------------------------------------------------------


class TestDelegateToolWithResult:
    async def test_grounded_dispatch(self) -> None:
        tool = DelegateTool()

        async def dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            return DelegationResult(content="found data", tools_used=["web_search"])

        tool.set_dispatch(dispatch)
        result = await tool.execute(task="find info", target_role="research")
        assert result.success
        assert "grounded=True" in result.output
        assert "found data" in result.output

    async def test_ungrounded_dispatch(self) -> None:
        tool = DelegateTool()

        async def dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            return DelegationResult(content="guess", tools_used=[])

        tool.set_dispatch(dispatch)
        result = await tool.execute(task="search for bugs", target_role="code")
        assert result.success
        assert "grounded=False" in result.output


# ---------------------------------------------------------------------------
# DelegateParallelTool with DelegationResult
# ---------------------------------------------------------------------------


class TestDelegateParallelToolWithResult:
    async def test_mixed_grounded_results(self) -> None:
        tool = DelegateParallelTool()

        async def dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            if "grounded" in task:
                return DelegationResult(content="data", tools_used=["exec"])
            return DelegationResult(content="guess", tools_used=[])

        tool.set_dispatch(dispatch)
        result = await tool.execute(
            subtasks=[
                {"task": "grounded task"},
                {"task": "ungrounded task"},
            ]
        )
        assert result.success
        assert "✓" in result.output
        assert "ungrounded" in result.output


# ---------------------------------------------------------------------------
# Scratchpad metadata and _grounded_tag
# ---------------------------------------------------------------------------


class TestScratchpadGroundedTag:
    async def test_write_with_metadata(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(
            role="code",
            label="result",
            content="hello",
            metadata={"grounded": True, "tools_used": ["exec"]},
        )
        entries = pad.list_entries()
        assert len(entries) == 1
        assert entries[0]["metadata"]["grounded"] is True

    async def test_read_shows_grounded_tag(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        entry_id = await pad.write(
            role="code",
            label="result",
            content="verified",
            metadata={"grounded": True, "tools_used": ["exec"]},
        )
        output = pad.read(entry_id)
        assert "✓" in output

    async def test_read_shows_ungrounded_tag(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        entry_id = await pad.write(
            role="research",
            label="guess",
            content="maybe",
            metadata={"grounded": False, "tools_used": []},
        )
        output = pad.read(entry_id)
        assert "⚠ungrounded" in output

    async def test_read_no_metadata_no_tag(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        entry_id = await pad.write(role="r", label="label", content="c")
        output = pad.read(entry_id)
        assert "✓" not in output
        assert "⚠" not in output

    async def test_read_all_shows_tags(self, tmp_path: Path) -> None:
        pad = Scratchpad(tmp_path)
        await pad.write(
            role="a",
            label="grounded",
            content="x",
            metadata={"grounded": True},
        )
        await pad.write(
            role="b",
            label="ungrounded",
            content="y",
            metadata={"grounded": False},
        )
        await pad.write(role="c", label="plain", content="z")
        output = pad.read()
        assert "✓" in output
        assert "⚠ungrounded" in output

    def test_grounded_tag_static_method(self) -> None:
        assert Scratchpad._grounded_tag({"metadata": {"grounded": True}}) == " ✓"
        assert Scratchpad._grounded_tag({"metadata": {"grounded": False}}) == " ⚠ungrounded"
        assert Scratchpad._grounded_tag({"metadata": {}}) == ""
        assert Scratchpad._grounded_tag({}) == ""
        assert Scratchpad._grounded_tag({"metadata": "not a dict"}) == ""
