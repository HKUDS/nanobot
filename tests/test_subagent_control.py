import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    return provider


def _make_manager(tmp_path: Path) -> SubagentManager:
    return SubagentManager(
        provider=_make_provider(),
        workspace=tmp_path,
        bus=MessageBus(),
        model="test-model",
    )


@pytest.mark.asyncio
async def test_subagent_list_returns_empty_when_no_tasks(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    assert manager.list_running() == []


@pytest.mark.asyncio
async def test_subagent_list_includes_running_tasks(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    task_id = "abc12345"
    sleeper = asyncio.create_task(asyncio.sleep(60))
    manager._running_tasks[task_id] = sleeper
    manager._task_meta[task_id] = {
        "label": "demo",
        "task": "do work",
        "started_at": "2026-01-01T00:00:00+00:00",
    }

    try:
        running = manager.list_running()
        assert len(running) == 1
        assert running[0]["id"] == task_id
        assert running[0]["label"] == "demo"
        assert running[0]["status"] == "running"
    finally:
        sleeper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sleeper


@pytest.mark.asyncio
async def test_subagent_kill_success(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    task_id = "deadbeef"
    sleeper = asyncio.create_task(asyncio.sleep(60))
    manager._running_tasks[task_id] = sleeper
    manager._task_meta[task_id] = {
        "label": "demo",
        "task": "do work",
        "started_at": "2026-01-01T00:00:00+00:00",
    }

    ok, message = await manager.kill(task_id)

    assert ok is True
    assert "cancel" in message.lower()
    assert task_id not in manager._running_tasks
    assert task_id not in manager._task_meta


@pytest.mark.asyncio
async def test_subagent_kill_nonexistent_task(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    ok, message = await manager.kill("missing")
    assert ok is False
    assert "not found" in message.lower()


@pytest.mark.asyncio
async def test_subagent_kill_handles_race_with_completed_task(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    task_id = "facefeed"
    done_task = asyncio.create_task(asyncio.sleep(0))
    manager._running_tasks[task_id] = done_task
    manager._task_meta[task_id] = {
        "label": "demo",
        "task": "do work",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    await done_task

    ok, message = await manager.kill(task_id)

    assert ok is False
    assert "already" in message.lower()
    assert task_id not in manager._running_tasks
    assert task_id not in manager._task_meta


@pytest.mark.asyncio
async def test_agent_loop_subagent_list_command_bypasses_model(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _make_provider()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/subagent list")
    )

    assert response is not None
    assert "No running subagents" in response.content
    provider.chat.assert_not_called()


@pytest.mark.asyncio
async def test_agent_loop_subagent_kill_nonexistent_bypasses_model(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _make_provider()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/subagent kill missing")
    )

    assert response is not None
    assert "not found" in response.content.lower()
    provider.chat.assert_not_called()


@pytest.mark.asyncio
async def test_agent_loop_subagent_kill_requires_id(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _make_provider()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/subagent kill")
    )

    assert response is not None
    assert "usage: /subagent kill <id>" in response.content.lower()
    provider.chat.assert_not_called()
