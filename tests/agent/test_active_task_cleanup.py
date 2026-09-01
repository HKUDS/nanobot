"""Tests for releasing active-task groups when their tasks finish (issue #5428)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop(*, tools_config=None):
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr,
    ):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            tools_config=tools_config,
        )
    return loop


async def _completed() -> None:
    return None


class TestActiveTaskCleanup:
    @pytest.mark.asyncio
    async def test_release_removes_group_when_last_task_finishes(self):
        loop = _make_loop()
        key = "session:abc"
        task = asyncio.create_task(_completed())
        await task
        loop._active_tasks[key] = {task}

        loop._release_active_task(task, key)

        assert key not in loop._active_tasks

    @pytest.mark.asyncio
    async def test_release_keeps_group_while_other_tasks_remain(self):
        loop = _make_loop()
        key = "session:abc"
        first = asyncio.create_task(_completed())
        second = asyncio.create_task(_completed())
        await asyncio.gather(first, second)
        loop._active_tasks[key] = {first, second}

        loop._release_active_task(first, key)

        assert loop._active_tasks[key] == {second}

    @pytest.mark.asyncio
    async def test_release_ignores_unknown_group(self):
        loop = _make_loop()
        task = asyncio.create_task(_completed())
        await task

        loop._release_active_task(task, "session:missing")

        assert loop._active_tasks == {}
