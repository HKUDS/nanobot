"""Tests for explicit subagent mailbox tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.subagent_mailbox import (
    CancelSubagentTool,
    PollSubagentsTool,
    WaitSubagentsTool,
)
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults


def _manager(tmp_path: Path) -> SubagentManager:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    )


def _bind(tool, session_key: str = "cli:test") -> None:
    tool.set_context(RequestContext(channel="cli", chat_id="test", session_key=session_key))


async def _drain(mgr: SubagentManager) -> None:
    tasks = list(mgr._running_tasks.values())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_wait_subagents_returns_result_once(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    mgr.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="worker result", messages=[], stop_reason="completed")
    )

    await mgr.spawn("do work", label="worker", session_key="cli:test")
    task_id = next(iter(mgr._running_tasks))
    await _drain(mgr)

    wait_tool = WaitSubagentsTool(mgr)
    _bind(wait_tool)

    first = await wait_tool.execute(task_id=task_id, timeout_seconds=0)
    second = await wait_tool.execute(task_id=task_id, timeout_seconds=0)

    assert "worker result" in first
    assert f"id: {task_id}" in first
    assert "already consumed" in second


@pytest.mark.asyncio
async def test_wait_subagents_reads_result_after_manager_recreation(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    mgr.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="durable worker result", messages=[], stop_reason="completed")
    )

    await mgr.spawn("do durable work", label="worker", session_key="cli:test")
    task_id = next(iter(mgr._running_tasks))
    await _drain(mgr)

    recreated = _manager(tmp_path)
    wait_tool = WaitSubagentsTool(recreated)
    poll_tool = PollSubagentsTool(recreated)
    _bind(wait_tool)
    _bind(poll_tool)

    first = await wait_tool.execute(task_id=task_id, timeout_seconds=0)
    after = await poll_tool.execute(task_id=task_id)

    assert "durable worker result" in first
    assert "result consumed" in after


@pytest.mark.asyncio
async def test_poll_subagents_reports_running_completed_and_not_found(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    release = asyncio.Event()

    async def _run(_spec):
        await release.wait()
        return AgentRunResult(final_content="done", messages=[], stop_reason="completed")

    mgr.runner.run = AsyncMock(side_effect=_run)
    await mgr.spawn("slow work", label="slow", session_key="cli:test")
    task_id = next(iter(mgr._running_tasks))

    poll_tool = PollSubagentsTool(mgr)
    _bind(poll_tool)

    running = await poll_tool.execute(task_id=task_id)
    missing = await poll_tool.execute(task_id="missing")
    release.set()
    await _drain(mgr)
    completed = await poll_tool.execute(task_id=task_id)

    assert "status: running" in running
    assert "not found" in missing
    assert "completed, result ready" in completed


@pytest.mark.asyncio
async def test_cancel_subagent_marks_cancelled_result(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    started = asyncio.Event()

    async def _run(_spec):
        started.set()
        await asyncio.Event().wait()

    mgr.runner.run = AsyncMock(side_effect=_run)
    await mgr.spawn("slow work", label="slow", session_key="cli:test")
    task_id = next(iter(mgr._running_tasks))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    cancel_tool = CancelSubagentTool(mgr)
    wait_tool = WaitSubagentsTool(mgr)
    _bind(cancel_tool)
    _bind(wait_tool)

    cancelled = await cancel_tool.execute(task_id=task_id)
    result = await wait_tool.execute(task_id=task_id, timeout_seconds=0)

    assert cancelled == f"Cancelled subagent task {task_id}."
    assert "status: cancelled" in result
    assert "Cancelled by manager." in result
