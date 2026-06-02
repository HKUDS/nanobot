"""Tests for memory_search and conversation_search tools (LM2-E)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.sanitize import L0CaptureRow
from nanobot.agent.layered_memory.search_budget import reset_memory_search_calls
from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.conversation_search import ConversationSearchTool
from nanobot.agent.tools.memory_search import MemorySearchTool
from nanobot.config.loader import ensure_config_models_built
from nanobot.config.schema import LayeredMemoryCaptureConfig, LayeredMemoryConfig, ToolsConfig


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _layered_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )


def _tools_config() -> ToolsConfig:
    ensure_config_models_built()
    return ToolsConfig()


def _memory_tool(workspace: Path) -> MemorySearchTool:
    ctx = ToolContext(
        config=_tools_config(),
        workspace=str(workspace),
        layered_memory=_layered_cfg(),
    )
    tool = MemorySearchTool.create(ctx)
    assert isinstance(tool, MemorySearchTool)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))
    reset_memory_search_calls()
    return tool


def _conversation_tool(workspace: Path) -> ConversationSearchTool:
    ctx = ToolContext(
        config=_tools_config(),
        workspace=str(workspace),
        layered_memory=_layered_cfg(),
    )
    tool = ConversationSearchTool.create(ctx)
    assert isinstance(tool, ConversationSearchTool)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))
    reset_memory_search_calls()
    return tool


@pytest.mark.asyncio
async def test_memory_search_finds_l1_atom(workspace: Path) -> None:
    store = L1Store(workspace)
    store.insert(
        session_key="cli:direct",
        memory_type="rule",
        content='只在用户明确说"提交/commit"时才执行 git commit',
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    tool = _memory_tool(workspace)
    tool._l1_store = store
    result = await tool.execute(query="git commit")
    assert isinstance(result, str)
    assert "Found 1 memory atom" in result
    assert "git commit" in result
    assert "[rule]" in result


@pytest.mark.asyncio
async def test_conversation_search_finds_l0_message(workspace: Path) -> None:
    l0 = L0Store(workspace)
    l0.append_messages(
        "cli:direct",
        "turn-1",
        [
            L0CaptureRow(
                role="user",
                content="以后别自动 git commit，只有我明确说 commit 才行",
                timestamp_ms=1,
            ),
        ],
    )
    tool = _conversation_tool(workspace)
    tool._l0_store = l0
    result = await tool.execute(query="git commit")
    assert isinstance(result, str)
    assert "Found 1 message" in result
    assert "git commit" in result
    assert "[user]" in result


@pytest.mark.asyncio
async def test_search_budget_limits_combined_calls(workspace: Path) -> None:
    cfg = _layered_cfg()
    cfg.recall.max_search_calls_per_turn = 2
    ctx = ToolContext(
        config=_tools_config(),
        workspace=str(workspace),
        layered_memory=cfg,
    )
    mem = MemorySearchTool.create(ctx)
    conv = ConversationSearchTool.create(ctx)
    assert isinstance(mem, MemorySearchTool)
    assert isinstance(conv, ConversationSearchTool)
    req = RequestContext(channel="cli", chat_id="direct", session_key="cli:direct")
    mem.set_context(req)
    conv.set_context(req)
    reset_memory_search_calls()

    assert "No memory atoms" in await mem.execute(query="alpha")
    assert "No conversation messages" in await conv.execute(query="beta")
    blocked = await mem.execute(query="gamma")
    assert "limit reached" in blocked


def test_tools_disabled_without_capture(workspace: Path) -> None:
    ctx = ToolContext(
        config=_tools_config(),
        workspace=str(workspace),
        layered_memory=LayeredMemoryConfig(enable=True),
    )
    assert MemorySearchTool.enabled(ctx) is False
    assert ConversationSearchTool.enabled(ctx) is False


def test_l0_search_messages(workspace: Path) -> None:
    store = L0Store(workspace)
    store.append_messages(
        "cli:direct",
        "t1",
        [L0CaptureRow(role="user", content="hello layered memory", timestamp_ms=1)],
    )
    hits = store.search_messages("layered", session_key="cli:direct", limit=5)
    assert len(hits) == 1
    assert "layered memory" in hits[0].content
