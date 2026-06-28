"""Per-spawn model override for subagents (issue #4231).

A spawned subagent inherits the parent agent's model by default, but ``spawn``
now accepts an optional ``model`` so the agent can delegate a heavy task to a
stronger model (or a simple one to a cheaper/faster model) for that subagent
only, without mutating the manager's shared model.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, SubagentStatus
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider


def _manager(tmp_path) -> SubagentManager:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "parent-model"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="parent-model",
        max_tool_result_chars=16_000,
    )
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()
    return sm


def _status() -> SubagentStatus:
    return SubagentStatus(task_id="t1", label="label", task_description="task", started_at=0.0)


@pytest.mark.asyncio
async def test_run_subagent_uses_override_model(tmp_path):
    sm = _manager(tmp_path)

    await sm._run_subagent(
        "t1", "task", "label", {"channel": "cli", "chat_id": "direct"}, _status(),
        model="strong-reasoner",
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.model == "strong-reasoner"
    # The override is per-spawn only: the manager's shared model is untouched.
    assert sm.model == "parent-model"


@pytest.mark.asyncio
async def test_run_subagent_defaults_to_manager_model(tmp_path):
    sm = _manager(tmp_path)

    await sm._run_subagent(
        "t1", "task", "label", {"channel": "cli", "chat_id": "direct"}, _status(),
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.model == "parent-model"


@pytest.mark.asyncio
async def test_spawn_tool_forwards_model_to_manager():
    manager = MagicMock()
    manager.get_running_count.return_value = 0
    manager.max_concurrent_subagents = 4
    manager.spawn = AsyncMock(return_value="started")

    tool = SpawnTool(manager=manager)
    await tool.execute(task="do the hard thing", model="strong-reasoner")

    assert manager.spawn.await_args.kwargs["model"] == "strong-reasoner"


@pytest.mark.asyncio
async def test_spawn_tool_model_defaults_to_none():
    manager = MagicMock()
    manager.get_running_count.return_value = 0
    manager.max_concurrent_subagents = 4
    manager.spawn = AsyncMock(return_value="started")

    tool = SpawnTool(manager=manager)
    await tool.execute(task="simple thing")

    assert manager.spawn.await_args.kwargs["model"] is None
