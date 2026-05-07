"""Focused tests for MyTool runtime sync side effects."""

from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.self import MyTool


@pytest.mark.asyncio
async def test_my_tool_max_iterations_syncs_subagent_limit() -> None:
    loop = MagicMock()
    loop.max_iterations = 40
    loop._runtime_vars = {}
    loop.subagents = MagicMock()
    loop.subagents.max_iterations = loop.max_iterations

    def _sync_subagent_runtime_limits() -> None:
        loop.subagents.max_iterations = loop.max_iterations

    loop._sync_subagent_runtime_limits = _sync_subagent_runtime_limits

    tool = MyTool(loop=loop)

    result = await tool.execute(action="set", key="max_iterations", value=80)

    assert "Set max_iterations = 80" in result
    assert loop.max_iterations == 80
    assert loop.subagents.max_iterations == 80
