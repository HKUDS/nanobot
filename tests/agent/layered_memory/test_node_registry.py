"""Tests for layered memory node registry (LM1-A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.layered_memory import LayeredMemoryFacade
from nanobot.agent.layered_memory.offload.node_registry import NodeRegistry, summarize_tool_result
from nanobot.config.schema import LayeredMemoryConfig


def test_upsert_creates_nodes_json(tmp_path: Path) -> None:
    registry = NodeRegistry(tmp_path, "webui:main")
    node = registry.upsert(
        node_id="call-1",
        tool="read_file",
        path=".nanobot/tool-results/webui_main/call-1.txt",
        summary="read config",
        chars=9000,
    )
    assert node.node_id == "call-1"
    assert registry.nodes_path.exists()
    data = json.loads(registry.nodes_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["tool"] == "read_file"
    assert data[0]["path"].endswith("call-1.txt")


def test_upsert_updates_existing_node(tmp_path: Path) -> None:
    registry = NodeRegistry(tmp_path, "sess")
    registry.upsert(
        node_id="call-1",
        tool="list_dir",
        path=None,
        summary="first",
        chars=10,
    )
    registry.upsert(
        node_id="call-1",
        tool="list_dir",
        path="out.txt",
        summary="second pass",
        chars=20,
    )
    nodes = registry.list_nodes()
    assert len(nodes) == 1
    assert nodes[0].summary.startswith("second")
    assert nodes[0].chars == 20
    assert nodes[0].path == "out.txt"


def test_summarize_tool_result_truncates() -> None:
    text = "a" * 200
    assert len(summarize_tool_result(text, max_chars=50)) == 50


def test_facade_register_writes_registry(tmp_path: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    facade = LayeredMemoryFacade(tmp_path, cfg)
    facade.register_tool_result(
        session_key="webui:main",
        node_id="call-x",
        tool_name="grep",
        persist_path=".nanobot/tool-results/x.txt",
        summary="matched lines",
        chars=5000,
    )
    registry = NodeRegistry(tmp_path, "webui:main")
    node = registry.get("call-x")
    assert node is not None
    assert node.tool == "grep"
    assert node.chars == 5000


@pytest.mark.asyncio
async def test_runner_registers_node_on_large_tool_result(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    facade = LayeredMemoryFacade(tmp_path, cfg)

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="ok",
                tool_calls=[ToolCallRequest(id="call_big", name="list_dir", arguments={})],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="y" * 10_000)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "run"}],
        tools=tools,
        model="test",
        max_iterations=2,
        workspace=tmp_path,
        session_key="test:runner",
        max_tool_result_chars=2048,
        layered_memory_facade=facade,
    ))

    registry = NodeRegistry(tmp_path, "test:runner")
    node = registry.get("call_big")
    assert node is not None
    assert node.path is not None
    assert node.chars >= 10_000
    tool_path = tmp_path / node.path
    assert tool_path.exists()


@pytest.mark.asyncio
async def test_runner_skips_registry_when_offload_disabled(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.runner import AgentRunSpec, AgentRunner
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    facade = LayeredMemoryFacade(tmp_path, LayeredMemoryConfig())

    provider = MagicMock()
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="ok",
                tool_calls=[ToolCallRequest(id="call_1", name="x", arguments={})],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="z" * 10_000)

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "run"}],
        tools=tools,
        model="test",
        max_iterations=2,
        workspace=tmp_path,
        session_key="sess",
        max_tool_result_chars=2048,
        layered_memory_facade=facade,
    ))
    assert not NodeRegistry(tmp_path, "sess").nodes_path.exists()
