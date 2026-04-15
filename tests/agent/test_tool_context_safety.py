"""Tests for tool routing context safety (no shared mutable state)."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


# ---------------------------------------------------------------------------
# Fake tool that captures _routing_context for assertions
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        value=StringSchema("A dummy value"),
        required=["value"],
    )
)
class _CaptureTool(Tool):
    """Captures the _routing_context it receives during execute()."""

    def __init__(self, tool_name: str = "capture"):
        self._tool_name = tool_name
        self.last_routing_context: dict | None = None

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return "Captures routing context for testing"

    async def execute(
        self,
        value: str = "",
        *,
        _routing_context: dict | None = None,
        **kwargs: Any,
    ) -> str:
        self.last_routing_context = _routing_context
        return f"ok:{value}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_execute_passes_routing_context() -> None:
    """ToolRegistry.execute() forwards routing_context to the tool."""
    registry = ToolRegistry()
    tool = _CaptureTool("capture")
    registry.register(tool)

    ctx = {"channel": "telegram", "chat_id": "12345", "session_key": "telegram:12345"}
    result = await registry.execute("capture", {"value": "hello"}, routing_context=ctx)

    assert result == "ok:hello"
    assert tool.last_routing_context == ctx


@pytest.mark.asyncio
async def test_registry_execute_without_routing_context() -> None:
    """When no routing_context is passed, tool receives None (backward compat)."""
    registry = ToolRegistry()
    tool = _CaptureTool("capture")
    registry.register(tool)

    result = await registry.execute("capture", {"value": "test"})

    assert result == "ok:test"
    assert tool.last_routing_context is None


@pytest.mark.asyncio
async def test_two_routing_contexts_do_not_interfere() -> None:
    """Two calls with different routing contexts don't overwrite each other."""
    registry = ToolRegistry()
    tool = _CaptureTool("capture")
    registry.register(tool)

    ctx_a = {"channel": "telegram", "chat_id": "aaa"}
    ctx_b = {"channel": "discord", "chat_id": "bbb"}

    result_a = await registry.execute("capture", {"value": "a"}, routing_context=ctx_a)
    captured_a = dict(tool.last_routing_context)

    result_b = await registry.execute("capture", {"value": "b"}, routing_context=ctx_b)
    captured_b = dict(tool.last_routing_context)

    assert result_a == "ok:a"
    assert result_b == "ok:b"
    assert captured_a == ctx_a
    assert captured_b == ctx_b
    assert captured_a != captured_b


@pytest.mark.asyncio
async def test_message_tool_uses_routing_context() -> None:
    """MessageTool.execute() uses _routing_context over self._default_*."""
    from nanobot.agent.tools.message import MessageTool

    sent: list = []

    async def fake_send(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=fake_send,
        default_channel="old_channel",
        default_chat_id="old_chat",
    )

    ctx = {"channel": "new_channel", "chat_id": "new_chat"}
    result = await tool.execute(content="hello", _routing_context=ctx)

    assert "Message sent to new_channel:new_chat" in result
    assert sent[0].channel == "new_channel"
    assert sent[0].chat_id == "new_chat"


@pytest.mark.asyncio
async def test_message_tool_fallback_to_defaults() -> None:
    """MessageTool falls back to self._default_* when no routing context."""
    from nanobot.agent.tools.message import MessageTool

    sent: list = []

    async def fake_send(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=fake_send,
        default_channel="fallback_ch",
        default_chat_id="fallback_id",
    )

    result = await tool.execute(content="hello")

    assert "Message sent to fallback_ch:fallback_id" in result


@pytest.mark.asyncio
async def test_spawn_tool_uses_routing_context() -> None:
    """SpawnTool.execute() uses _routing_context for origin info."""
    from unittest.mock import AsyncMock, MagicMock
    from nanobot.agent.tools.spawn import SpawnTool

    manager = MagicMock()
    manager.spawn = AsyncMock(return_value="spawned")

    tool = SpawnTool(manager=manager)
    ctx = {"channel": "telegram", "chat_id": "42", "session_key": "telegram:42"}
    await tool.execute(task="do something", _routing_context=ctx)

    manager.spawn.assert_called_once_with(
        task="do something",
        label=None,
        origin_channel="telegram",
        origin_chat_id="42",
        session_key="telegram:42",
    )


@pytest.mark.asyncio
async def test_spawn_tool_fallback_to_instance_defaults() -> None:
    """SpawnTool falls back to instance defaults when no routing context."""
    from unittest.mock import AsyncMock, MagicMock
    from nanobot.agent.tools.spawn import SpawnTool

    manager = MagicMock()
    manager.spawn = AsyncMock(return_value="spawned")

    tool = SpawnTool(manager=manager)
    await tool.execute(task="do something")

    manager.spawn.assert_called_once_with(
        task="do something",
        label=None,
        origin_channel="cli",
        origin_chat_id="direct",
        session_key="cli:direct",
    )
