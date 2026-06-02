"""Tests for read_memory_node tool (LM1-D)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.layered_memory.offload.node_registry import NodeRegistry
from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.memory_node import ReadMemoryNodeTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import ensure_config_models_built
from nanobot.config.schema import LayeredMemoryConfig, ToolsConfig


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _tools_config(**kwargs: object) -> ToolsConfig:
    ensure_config_models_built()
    return ToolsConfig(**kwargs)


def _tool(workspace: Path, *, layered: LayeredMemoryConfig | None = None) -> ReadMemoryNodeTool:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    ctx = ToolContext(
        config=_tools_config(),
        workspace=str(workspace),
        layered_memory=layered or cfg,
    )
    tool = ReadMemoryNodeTool.create(ctx)
    assert isinstance(tool, ReadMemoryNodeTool)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))
    return tool


@pytest.mark.asyncio
async def test_read_memory_node_returns_persisted_content(workspace: Path) -> None:
    persist_rel = ".nanobot/tool-results/cli_direct/call_big.txt"
    persist_path = workspace / persist_rel
    persist_path.parent.mkdir(parents=True, exist_ok=True)
    persist_path.write_text("line one\nline two\n", encoding="utf-8")

    registry = NodeRegistry(workspace, "cli:direct")
    registry.upsert(
        node_id="call_big",
        tool="read_file",
        path=persist_rel,
        summary="big file",
        chars=20_000,
    )

    tool = _tool(workspace)
    result = await tool.execute(node_id="call_big")
    assert isinstance(result, str)
    assert "[memory node call_big" in result
    assert "line one" in result
    assert "line two" in result


@pytest.mark.asyncio
async def test_read_memory_node_missing_id_hint(workspace: Path) -> None:
    registry = NodeRegistry(workspace, "cli:direct")
    registry.upsert(
        node_id="call_a",
        tool="grep",
        path="x.txt",
        summary="a",
        chars=1,
    )

    tool = _tool(workspace)
    result = await tool.execute(node_id="missing")
    assert "not found" in result
    assert "call_a" in result


@pytest.mark.asyncio
async def test_read_memory_node_no_persist_path(workspace: Path) -> None:
    NodeRegistry(workspace, "cli:direct").upsert(
        node_id="call_small",
        tool="list_dir",
        path=None,
        summary="small output",
        chars=50,
    )

    tool = _tool(workspace)
    result = await tool.execute(node_id="call_small")
    assert "no persisted file" in result
    assert "call_small" in result


def test_read_memory_node_disabled_without_config(workspace: Path) -> None:
    ctx = ToolContext(config=_tools_config(), workspace=str(workspace), layered_memory=None)
    assert ReadMemoryNodeTool.enabled(ctx) is False


def test_read_memory_node_registers_when_offload_on(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    ctx = ToolContext(config=_tools_config(), workspace=str(workspace), layered_memory=cfg)
    registry = ToolRegistry()
    from nanobot.agent.tools.loader import ToolLoader

    names = ToolLoader().load(ctx, registry, scope="core")
    assert "read_memory_node" in names


@pytest.mark.asyncio
async def test_read_memory_node_respects_workspace_boundary(workspace: Path) -> None:
    outside = Path("/etc/passwd")
    registry = NodeRegistry(workspace, "cli:direct")
    registry.upsert(
        node_id="evil",
        tool="read_file",
        path=str(outside),
        summary="x",
        chars=100,
    )

    lm = LayeredMemoryConfig(enable=True)
    lm.offload.enable = True
    ctx = ToolContext(
        config=_tools_config(restrict_to_workspace=True),
        workspace=str(workspace),
        layered_memory=lm,
    )
    tool = ReadMemoryNodeTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))
    result = await tool.execute(node_id="evil")
    assert "outside allowed directory" in result.lower() or "Error:" in result
