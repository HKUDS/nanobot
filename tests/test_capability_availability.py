"""Tests for Phase A of the capability registry: tool availability protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.builtin.delegate import DelegateParallelTool, DelegateTool
from nanobot.tools.builtin.email import CheckEmailTool
from nanobot.tools.builtin.web import WebSearchTool
from nanobot.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class AlwaysAvailableTool(Tool):
    """A tool that is always available (default check_available)."""

    readonly = True
    name = "always_ok"
    description = "Always available"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class NeverAvailableTool(Tool):
    """A tool that reports itself as unavailable."""

    readonly = True
    name = "never_ok"
    description = "Never available"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def check_available(self) -> tuple[bool, str | None]:
        return False, "missing dependency XYZ"

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    return ws


# ---------------------------------------------------------------------------
# Tool.check_available() default behaviour
# ---------------------------------------------------------------------------


class TestToolCheckAvailableDefault:
    def test_default_returns_available(self) -> None:
        tool = AlwaysAvailableTool()
        available, reason = tool.check_available()
        assert available is True
        assert reason is None

    def test_override_returns_unavailable(self) -> None:
        tool = NeverAvailableTool()
        available, reason = tool.check_available()
        assert available is False
        assert reason == "missing dependency XYZ"


# ---------------------------------------------------------------------------
# WebSearchTool.check_available()
# ---------------------------------------------------------------------------


class TestWebSearchToolAvailability:
    def test_available_with_api_key(self) -> None:
        tool = WebSearchTool(api_key="test-key")
        available, reason = tool.check_available()
        assert available is True
        assert reason is None

    def test_unavailable_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        tool = WebSearchTool(api_key=None)
        available, reason = tool.check_available()
        assert available is False
        assert "API key" in (reason or "")


# ---------------------------------------------------------------------------
# CheckEmailTool.check_available()
# ---------------------------------------------------------------------------


class TestCheckEmailToolAvailability:
    def test_available_with_fetch_callback(self) -> None:
        tool = CheckEmailTool(fetch_callback=lambda a, b, c: [])
        available, reason = tool.check_available()
        assert available is True

    def test_available_with_unread_callback(self) -> None:
        tool = CheckEmailTool(fetch_unread_callback=lambda n: [])
        available, reason = tool.check_available()
        assert available is True

    def test_unavailable_without_callbacks(self) -> None:
        tool = CheckEmailTool()
        available, reason = tool.check_available()
        assert available is False
        assert "not configured" in (reason or "").lower()


# ---------------------------------------------------------------------------
# DelegateTool.check_available()
# ---------------------------------------------------------------------------


class TestDelegateToolAvailability:
    def test_unavailable_without_dispatch(self) -> None:
        tool = DelegateTool()
        available, reason = tool.check_available()
        assert available is False
        assert reason is not None

    def test_available_with_dispatch(self) -> None:
        tool = DelegateTool()

        async def fake_dispatch(role: str, task: str, ctx: str | None) -> None:
            pass

        tool.set_dispatch(fake_dispatch)  # type: ignore[arg-type]
        available, reason = tool.check_available()
        assert available is True


class TestDelegateParallelToolAvailability:
    def test_unavailable_without_dispatch(self) -> None:
        tool = DelegateParallelTool()
        available, reason = tool.check_available()
        assert available is False

    def test_available_with_dispatch(self) -> None:
        tool = DelegateParallelTool()

        async def fake_dispatch(role: str, task: str, ctx: str | None) -> None:
            pass

        tool.set_dispatch(fake_dispatch)  # type: ignore[arg-type]
        available, reason = tool.check_available()
        assert available is True


# ---------------------------------------------------------------------------
# ToolRegistry.get_definitions() filtering
# ---------------------------------------------------------------------------


class TestRegistryAvailabilityFiltering:
    def test_get_definitions_excludes_unavailable(self) -> None:
        reg = ToolRegistry()
        reg.register(AlwaysAvailableTool())
        reg.register(NeverAvailableTool())

        defs = reg.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "always_ok" in names
        assert "never_ok" not in names

    def test_get_definitions_includes_all_when_available(self) -> None:
        reg = ToolRegistry()
        reg.register(AlwaysAvailableTool())
        reg.register(WebSearchTool(api_key="key"))

        defs = reg.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "always_ok" in names
        assert "web_search" in names

    def test_get_unavailable_summary_lists_reasons(self) -> None:
        reg = ToolRegistry()
        reg.register(AlwaysAvailableTool())
        reg.register(NeverAvailableTool())

        summary = reg.get_unavailable_summary()
        assert "never_ok" in summary
        assert "missing dependency XYZ" in summary
        assert "always_ok" not in summary

    def test_get_unavailable_summary_empty_when_all_available(self) -> None:
        reg = ToolRegistry()
        reg.register(AlwaysAvailableTool())
        assert reg.get_unavailable_summary() == ""

    def test_execute_still_works_for_unavailable_tool(self) -> None:
        """Unavailable tools are hidden from definitions but can still be executed."""
        reg = ToolRegistry()
        reg.register(NeverAvailableTool())
        # Tool is still registered and executable
        assert reg.has("never_ok")
        assert reg.get("never_ok") is not None


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------


class TestSystemPromptUnavailableInjection:
    def test_unavailable_tools_section_injected(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        builder = ContextBuilder(ws)
        builder.set_unavailable_tools_fn(lambda: "- web_search: no API key")

        prompt = builder.build_system_prompt()
        assert "# Unavailable Tools" in prompt
        assert "web_search" in prompt
        assert "no API key" in prompt

    def test_no_section_when_all_available(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        builder = ContextBuilder(ws)
        builder.set_unavailable_tools_fn(lambda: "")

        prompt = builder.build_system_prompt()
        assert "# Unavailable Tools" not in prompt

    def test_no_section_when_no_fn_set(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        builder = ContextBuilder(ws)

        prompt = builder.build_system_prompt()
        assert "# Unavailable Tools" not in prompt

    def test_integration_with_registry(self, tmp_path: Path) -> None:
        """End-to-end: registry -> callback -> system prompt."""
        ws = _workspace(tmp_path)
        reg = ToolRegistry()
        reg.register(AlwaysAvailableTool())
        reg.register(NeverAvailableTool())

        builder = ContextBuilder(ws)
        builder.set_unavailable_tools_fn(reg.get_unavailable_summary)

        prompt = builder.build_system_prompt()
        assert "# Unavailable Tools" in prompt
        assert "never_ok" in prompt
        assert "missing dependency XYZ" in prompt
