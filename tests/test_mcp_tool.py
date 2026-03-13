from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry


class _FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture(autouse=True)
def _fake_mcp_module(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = ModuleType("mcp")
    mod.types = SimpleNamespace(TextContent=_FakeTextContent)
    monkeypatch.setitem(sys.modules, "mcp", mod)


def _make_wrapper(
    session: object = None,
    *,
    timeout: float = 0.1,
    input_schema: dict | None = None,
) -> MCPToolWrapper:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema=input_schema or {"type": "object", "properties": {}},
    )
    return MCPToolWrapper(
        session or SimpleNamespace(), "test", tool_def, tool_timeout=timeout
    )


@pytest.mark.asyncio
async def test_execute_returns_text_blocks() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        assert arguments == {"value": 1}
        return SimpleNamespace(content=[_FakeTextContent("hello"), 42])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute(value=1)

    assert result == "hello\n42"


@pytest.mark.asyncio
async def test_execute_returns_timeout_message() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=0.01)

    result = await wrapper.execute()

    assert result == "(MCP tool call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_execute_handles_server_cancelled_error() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise asyncio.CancelledError()

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call was cancelled)"


@pytest.mark.asyncio
async def test_execute_re_raises_external_cancellation() -> None:
    started = asyncio.Event()

    async def call_tool(_name: str, arguments: dict) -> object:
        started.set()
        await asyncio.sleep(60)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=10)
    task = asyncio.create_task(wrapper.execute())
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_handles_generic_exception() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise RuntimeError("boom")

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call failed: RuntimeError)"


# --- Summary mode and promotion tests ---


def test_summary_only_default() -> None:
    wrapper = _make_wrapper()
    assert wrapper.is_summary_only is True


def test_promote_to_full() -> None:
    wrapper = _make_wrapper()
    wrapper.promote_to_full()
    assert wrapper.is_summary_only is False


def test_to_summary_schema() -> None:
    wrapper = _make_wrapper(
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    schema = wrapper.to_summary_schema()
    assert schema == {
        "type": "function",
        "function": {
            "name": "mcp_test_demo",
            "description": "demo tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_get_full_schema_text() -> None:
    import json

    wrapper = _make_wrapper(
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
        },
    )
    text = wrapper.get_full_schema_text()
    parsed = json.loads(text)
    assert parsed["function"]["parameters"]["properties"]["q"]["type"] == "string"


@pytest.mark.asyncio
async def test_registry_intercepts_summary_only_tool() -> None:
    wrapper = _make_wrapper()
    registry = ToolRegistry()
    registry.register(wrapper)

    result = await registry.execute("mcp_test_demo", {})

    assert "requires parameters" in result
    assert "full schema" in result.lower()
    assert wrapper.is_summary_only is False


@pytest.mark.asyncio
async def test_registry_returns_full_schema_after_promotion() -> None:
    wrapper = _make_wrapper(
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
        },
    )
    registry = ToolRegistry()
    registry.register(wrapper)

    # Before promotion: summary schema (empty properties)
    defs = registry.get_definitions()
    assert defs[0]["function"]["parameters"]["properties"] == {}

    # Promote
    wrapper.promote_to_full()

    # After promotion: full schema with properties
    defs = registry.get_definitions()
    assert "q" in defs[0]["function"]["parameters"]["properties"]


# --- Idle demotion tests ---


def test_idle_rounds_increment() -> None:
    wrapper = _make_wrapper()
    wrapper.promote_to_full()
    assert wrapper.idle_rounds == 0

    wrapper.tick_idle()
    wrapper.tick_idle()
    assert wrapper.idle_rounds == 2


def test_mark_used_resets_idle() -> None:
    wrapper = _make_wrapper()
    wrapper.promote_to_full()
    wrapper.tick_idle()
    wrapper.tick_idle()
    wrapper.mark_used()
    assert wrapper.idle_rounds == 0


def test_tick_idle_noop_when_summary() -> None:
    wrapper = _make_wrapper()
    assert wrapper.is_summary_only is True
    wrapper.tick_idle()
    wrapper.tick_idle()
    # idle_rounds should stay 0 when in summary mode
    assert wrapper.idle_rounds == 0


def test_demote_to_summary() -> None:
    wrapper = _make_wrapper()
    wrapper.promote_to_full()
    assert wrapper.is_summary_only is False
    wrapper.demote_to_summary()
    assert wrapper.is_summary_only is True
    assert wrapper.idle_rounds == 0


def test_registry_auto_demotes_idle_tool() -> None:
    from nanobot.agent.tools.registry import _MCP_IDLE_DEMOTE_ROUNDS

    wrapper = _make_wrapper(
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
        },
    )
    wrapper.promote_to_full()
    registry = ToolRegistry()
    registry.register(wrapper)

    # Each get_definitions() call ticks idle once
    for _ in range(_MCP_IDLE_DEMOTE_ROUNDS - 1):
        defs = registry.get_definitions()
        # Still full — not yet at threshold
        assert "q" in defs[0]["function"]["parameters"]["properties"]

    # One more round tips it over
    defs = registry.get_definitions()
    assert defs[0]["function"]["parameters"]["properties"] == {}
    assert wrapper.is_summary_only is True


@pytest.mark.asyncio
async def test_registry_execute_resets_idle() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        return SimpleNamespace(content=[_FakeTextContent("ok")])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))
    wrapper.promote_to_full()
    registry = ToolRegistry()
    registry.register(wrapper)

    # Tick idle a couple of times
    registry.get_definitions()
    registry.get_definitions()
    assert wrapper.idle_rounds == 2

    # Execute resets idle
    await registry.execute("mcp_test_demo", {})
    assert wrapper.idle_rounds == 0
