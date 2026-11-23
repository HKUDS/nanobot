from __future__ import annotations

import asyncio
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.exec_session import (
    ExecSessionManager,
    ExecSessionTool,
    ListExecSessionsTool,
)
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.rg import RgTool
from nanobot.agent.tools.shell import ExecTool


async def _start_gated(tool: ExecTool, gate: Path) -> str:
    code = (
        "import time; from pathlib import Path; "
        f"gate=Path({str(gate)!r})\n"
        "while not gate.exists(): time.sleep(0.01)\n"
        "print('retained result')"
    )
    result = await tool.execute(command=[sys.executable, "-u", "-c", code], yield_time_ms=0)
    match = re.search(r"session_id:\s*([0-9a-f]+)", result)
    assert match, result
    return match.group(1)


async def _wait_finished(manager: ExecSessionManager, owner: str | None, session_id: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sessions = await manager.list(owner_session_key=owner)
        if any(info.session_id == session_id and info.finish_reason == "exit" for info in sessions):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"session {session_id} did not finish")


@pytest.mark.parametrize("tool_name", [
    "exec",
    pytest.param("rg", marks=pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")),
])
async def test_finished_results_do_not_block_other_owner_tools(tmp_path, tool_name):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)
    owner_a = RequestContext(channel="cli", chat_id="a", session_key="cli:a")
    owner_b = RequestContext(channel="cli", chat_id="b", session_key="cli:b")
    try:
        with request_context(owner_a):
            oldest = await _start_gated(tool, tmp_path / "first")
            newest = await _start_gated(tool, tmp_path / "second")
        for gate, sid in [("first", oldest), ("second", newest)]:
            (tmp_path / gate).touch()
            await _wait_finished(manager, owner_a.session_key, sid)

        with request_context(owner_b):
            assert await ListExecSessionsTool(manager=manager).execute() == "No active exec sessions."
            assert is_tool_error_result(await session_tool.execute(session_id=newest, timeout_ms=0))
            if tool_name == "rg":
                result = await RgTool(working_dir=str(tmp_path), session_manager=manager).execute(
                    args=["--version"],
                )
                assert "ripgrep" in result
            else:
                result = await tool.execute(command=[sys.executable, "-c", "print('other owner')"])
                assert "other owner" in result
            assert not is_tool_error_result(result), result
            assert "Exit code: 0" in result

        with request_context(owner_a):
            remaining = await manager.list(owner_session_key=owner_a.session_key)
            assert [info.session_id for info in remaining] == [newest]
            result = await session_tool.execute(session_id=newest, timeout_ms=0)
            assert "retained result" in result
            assert "Exit code: 0" in result
    finally:
        await manager.close_all()


async def test_capacity_preserves_running_work_and_bounds_completed_results(tmp_path):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    try:
        running = await _start_gated(tool, tmp_path / "running")
        latest = await _start_gated(tool, tmp_path / "finished-0")
        rejected = await tool.execute(command=[sys.executable, "-c", "print('over capacity')"])
        assert is_tool_error_result(rejected)
        assert "maximum exec sessions reached (2)" in rejected
        for index in range(4):
            (tmp_path / f"finished-{index}").touch()
            await _wait_finished(manager, None, latest)
            latest = await _start_gated(tool, tmp_path / f"finished-{index + 1}")
            sessions = await manager.list()
            assert {info.session_id for info in sessions} == {running, latest}
            assert all(info.finish_reason is None for info in sessions)
    finally:
        await manager.close_all()
