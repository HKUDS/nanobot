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
from nanobot.execution import processes


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
            assert {info.session_id for info in remaining} == {oldest, newest}
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
        quick = await tool.execute(command=[sys.executable, "-c", "print('hello')"])
        assert "hello" in quick and "Exit code: 0" in quick
        completed = []
        for index in range(4):
            (tmp_path / f"finished-{index}").touch()
            await _wait_finished(manager, None, latest)
            completed.append(latest)
            latest = await _start_gated(tool, tmp_path / f"finished-{index + 1}")
            sessions = await manager.list()
            assert {s.session_id for s in sessions if not s.finish_reason} == {running, latest}
            assert {s.session_id for s in sessions if s.finish_reason} == set(completed[-2:])
    finally:
        await manager.close_all()


async def test_concurrent_promotions_wait_for_tree_cleanup_and_retain_owner_results(tmp_path, monkeypatch):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)
    owner = RequestContext(channel="cli", chat_id="a", session_key="cli:a")
    entered, release = asyncio.Event(), asyncio.Event()
    promotions = []
    try:
        first = await _start_gated(tool, tmp_path / "first")
        with request_context(owner):
            second = await _start_gated(tool, tmp_path / "second")
        victim = manager._sessions[first]
        kill = victim._kill

        async def slow_cleanup():
            entered.set()
            await release.wait()
            await kill()

        monkeypatch.setattr(victim, "_kill", slow_cleanup)
        promotions.append(asyncio.create_task(_start_gated(tool, tmp_path / "third")))
        await asyncio.wait_for(entered.wait(), 5)
        promotions.append(asyncio.create_task(_start_gated(tool, tmp_path / "fourth")))
        quick = await tool.execute(command=[sys.executable, "-c", "print('not a promotion')"])
        assert "Exit code: 0" in quick
        assert not any(task.done() for task in promotions)
        assert [s.session_id for s in await manager.list()] == [first]
        assert (await manager.list(owner_session_key=owner.session_key))[0].session_id == second
        with request_context(owner):
            denied = await session_tool.execute(session_id=first, input="intruder", timeout_ms=0)
            assert denied == f"Error: exec session not found: {first!r}"

        release.set()
        third, fourth = await asyncio.wait_for(asyncio.gather(*promotions), 5)
        assert victim.process.returncode is not None
        assert {s.session_id for s in await manager.list() if not s.finish_reason} == {third, fourth}
        first_result = await session_tool.execute(session_id=first, timeout_ms=0)
        with request_context(owner):
            second_result = await session_tool.execute(session_id=second, timeout_ms=0)
        for result in (first_result, second_result):
            assert not is_tool_error_result(result)
            assert "Session terminated. Reason: preempted_capacity." in result
    finally:
        release.set()
        await asyncio.gather(*promotions, return_exceptions=True)
        await manager.close_all()


async def test_failed_eviction_keeps_victim_and_reaps_unpromoted_candidate(tmp_path, monkeypatch):
    manager = ExecSessionManager(max_sessions=1, max_foreground=1)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    try:
        sid = await _start_gated(tool, tmp_path / "old")
        victim = manager._sessions[sid]
        kill = victim._kill

        async def fail():
            raise OSError("tree cleanup not confirmed")

        spawn = processes.spawn_process_tree
        children = []

        async def capture(*args, **kwargs):
            tree = await spawn(*args, **kwargs)
            children.append(tree.process)
            return tree

        monkeypatch.setattr(victim, "_kill", fail)
        monkeypatch.setattr(processes, "spawn_process_tree", capture)
        result = await tool.execute(command=[sys.executable, "-c", "input()"], yield_time_ms=0)
        assert is_tool_error_result(result) and "tree cleanup not confirmed" in result
        child, = children
        assert child.returncode is not None
        info, = await manager.list()
        assert info.session_id == sid and info.stopping and info.cleanup_error

        monkeypatch.setattr(victim, "_kill", kill)
        new = await _start_gated(tool, tmp_path / "new")
        assert {s.session_id: s.finish_reason for s in await manager.list()} == {
            sid: "preempted_capacity", new: None,
        }
    finally:
        monkeypatch.undo()
        await manager.close_all()


@pytest.mark.parametrize("fail_cleanup", [False, True])
async def test_full_promotion_joins_owner_cleanup_before_preempting(tmp_path, monkeypatch, fail_cleanup):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    owner = RequestContext(channel="cli", chat_id="retiring", session_key="cli:retiring")
    cleaning, promoting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        oldest = await _start_gated(tool, tmp_path / "oldest")
        with request_context(owner):
            newer = await _start_gated(tool, tmp_path / "newer")
        retiring = manager._sessions[newer]
        kill = retiring._kill

        async def gated_cleanup():
            cleaning.set()
            await release.wait()
            if fail_cleanup:
                raise OSError("retirement unconfirmed")
            await kill()

        monkeypatch.setattr(retiring, "_kill", gated_cleanup)
        stopping = asyncio.create_task(manager.terminate_by_owner(owner.session_key))
        tasks.append(stopping)
        await asyncio.wait_for(cleaning.wait(), 5)
        promote = manager._promote

        async def observe_promotion(session):
            promoting.set()
            return await promote(session)

        monkeypatch.setattr(manager, "_promote", observe_promotion)
        candidate = asyncio.create_task(tool.execute(command=[sys.executable, "-c", "input()"], yield_time_ms=0))
        tasks.append(candidate)
        await asyncio.wait_for(promoting.wait(), 5)
        release.set()
        result = await asyncio.wait_for(candidate, 5)
        if fail_cleanup:
            with pytest.raises(OSError, match="retirement unconfirmed"):
                await stopping
            assert is_tool_error_result(result)
            assert [s.session_id for s in await manager.list()] == [oldest]
            failed, = await manager.list(owner_session_key=owner.session_key)
            assert failed.session_id == newer and failed.cleanup_error
            monkeypatch.setattr(retiring, "_kill", kill)
            assert await manager.terminate_by_owner(owner.session_key) == 1
        else:
            assert await stopping == 1
            assert "Process running. session_id:" in result
        info = next(s for s in await manager.list() if s.session_id == oldest)
        assert info.returncode is None and not info.stopping
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        monkeypatch.undo()
        await manager.close_all()
