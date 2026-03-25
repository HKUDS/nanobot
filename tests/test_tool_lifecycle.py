"""Tests for Tool lifecycle hooks."""

from __future__ import annotations

from typing import Any

from nanobot.tools.base import Tool, ToolResult


class StubTool(Tool):
    """Minimal concrete tool for testing base class hooks."""

    name = "stub"
    description = "stub"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class TestToolLifecycleDefaults:
    def test_set_context_is_noop(self) -> None:
        tool = StubTool()
        tool.set_context(channel="ch", chat_id="123")  # should not raise

    def test_set_context_accepts_kwargs(self) -> None:
        tool = StubTool()
        tool.set_context(channel="ch", chat_id="123", session_key="s", extra="ignored")

    def test_on_turn_start_is_noop(self) -> None:
        tool = StubTool()
        tool.on_turn_start()  # should not raise

    def test_on_session_change_is_noop(self) -> None:
        tool = StubTool()
        tool.on_session_change(scratchpad=None)  # should not raise

    def test_sent_in_turn_defaults_false(self) -> None:
        tool = StubTool()
        assert tool.sent_in_turn is False
