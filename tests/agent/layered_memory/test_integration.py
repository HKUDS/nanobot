"""LM2-F integration tests for LayeredMemoryFacade."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.facade import LayeredMemoryFacade
from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.conversation_search import ConversationSearchTool
from nanobot.agent.tools.memory_search import MemorySearchTool
from nanobot.config.loader import ensure_config_models_built
from nanobot.config.schema import (
    LayeredMemoryCaptureConfig,
    LayeredMemoryConfig,
    LayeredMemoryOffloadConfig,
    LayeredMemoryRecallConfig,
    ToolsConfig,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _full_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        offload=LayeredMemoryOffloadConfig(enable=True),
        capture=LayeredMemoryCaptureConfig(enable=True),
        recall=LayeredMemoryRecallConfig(enable=True),
    )


@pytest.mark.asyncio
async def test_runtime_lines_combines_canvas_and_recall(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace, _full_cfg())
    store = L1Store(workspace)
    store.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="Gateway default port is 8765",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    facade._l1_store = store
    lines = await facade.runtime_lines("gateway port", "cli:direct")
    joined = "\n".join(lines)
    assert "[Recalled memories]" in joined or "8765" in joined
    assert "[Memory tools]" in joined


@pytest.mark.asyncio
async def test_runtime_lines_empty_when_subagent_defaults(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace, _full_cfg())
    lines = await facade.runtime_lines("hello", "cli:direct", is_subagent=True)
    assert lines == []


@pytest.mark.asyncio
async def test_close_shuts_down_pipeline(workspace: Path) -> None:
    facade = LayeredMemoryFacade(workspace, _full_cfg())
    await facade.close()
    assert facade._l0_store._conn is None
    assert facade._l1_store._conn is None


def test_subagent_tool_context_disables_memory_search(workspace: Path) -> None:
    ensure_config_models_built()
    ctx = ToolContext(
        config=ToolsConfig(),
        workspace=str(workspace),
        layered_memory=_full_cfg(),
        is_subagent=True,
    )
    assert MemorySearchTool.enabled(ctx) is False
    assert ConversationSearchTool.enabled(ctx) is False
