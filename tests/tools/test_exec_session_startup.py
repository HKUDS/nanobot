from __future__ import annotations

import asyncio
import sys

import pytest

from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.shell import ExecTool
from nanobot.execution import processes


async def test_owner_cancellation_during_startup_preserves_other_execution(tmp_path, monkeypatch):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    blocked_command = [sys.executable, "-u", "-c", "print('blocked launch')"]
    entered = asyncio.Event()
    release = asyncio.Event()
    spawn = processes.spawn_process_tree

    async def gated_spawn(command, cwd, env, shell_program, login, *, stdin):
        if command == blocked_command:
            entered.set()
            await release.wait()
        return await spawn(command, cwd, env, shell_program, login, stdin=stdin)

    monkeypatch.setattr(processes, "spawn_process_tree", gated_spawn)
    token = bind_request_context(RequestContext(channel="cli", chat_id="a", session_key="cli:a"))
    try:
        blocked = asyncio.create_task(tool.execute(command=blocked_command, yield_time_ms=0))
    finally:
        reset_request_context(token)
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        token = bind_request_context(RequestContext(channel="cli", chat_id="b", session_key="cli:b"))
        try:
            other = await asyncio.wait_for(
                tool.execute(command=[sys.executable, "-u", "-c", "print('other completed')"]),
                timeout=10,
            )
        finally:
            reset_request_context(token)
        assert "other completed" in other
        assert "Exit code: 0" in other
        assert await asyncio.wait_for(manager.terminate_by_owner("cli:a"), timeout=5) == 1
        with pytest.raises(asyncio.CancelledError):
            await blocked
        continued = await tool.execute(command=[sys.executable, "-u", "-c", "print('slot released')"])
        assert "slot released" in continued
        assert "Exit code: 0" in continued
    finally:
        release.set()
        await asyncio.gather(blocked, return_exceptions=True)
        await manager.close_all()


@pytest.mark.parametrize("stop", ["caller", "owner", "shutdown"])
async def test_foreground_admission_counts_spawn_and_cancels_queued_work(tmp_path, monkeypatch, stop):
    manager = ExecSessionManager(max_foreground=1, max_sessions=1)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    entered, release = asyncio.Event(), asyncio.Event()
    started = []
    spawn = processes.spawn_process_tree

    async def gated_spawn(command, *args, **kwargs):
        started.append(command[-1])
        entered.set()
        await release.wait()
        return await spawn(command, *args, **kwargs)

    monkeypatch.setattr(processes, "spawn_process_tree", gated_spawn)
    first = asyncio.create_task(tool.execute(command=[sys.executable, "-c", "print(1)"]))
    queued = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        token = bind_request_context(RequestContext(channel="cli", chat_id="q", session_key="cli:q"))
        try:
            queued = asyncio.create_task(tool.execute(command=[sys.executable, "-c", "print(2)"]))
        finally:
            reset_request_context(token)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert await manager.list() == []
        assert started == ["print(1)"] and manager.has_pending_work
        if stop == "caller":
            queued.cancel()
        elif stop == "owner":
            assert await manager.terminate_by_owner("cli:q") == 1
        else:
            assert await manager.close_all() == 2
        with pytest.raises(asyncio.CancelledError):
            await queued
        release.set()
        if stop == "shutdown":
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            assert "Exit code: 0" in await asyncio.wait_for(first, 5)
        assert started == ["print(1)"] and not manager.has_pending_work
    finally:
        release.set()
        await manager.close_all()
        await asyncio.gather(first, *([queued] if queued else []), return_exceptions=True)


async def test_close_owns_late_spawn_even_if_close_waiter_is_cancelled(tmp_path, monkeypatch):
    manager = ExecSessionManager(max_foreground=1)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    spawned, interrupted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    spawn = processes.spawn_process_tree
    trees = []

    async def late_handoff(*args, **kwargs):
        tree = await spawn(*args, **kwargs)
        trees.append(tree)
        spawned.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            interrupted.set()
            await release.wait()
        return tree

    monkeypatch.setattr(processes, "spawn_process_tree", late_handoff)
    call = asyncio.create_task(tool.execute(command=[sys.executable, "-c", "input()"], yield_time_ms=0))
    try:
        await asyncio.wait_for(spawned.wait(), 5)
        closing = asyncio.create_task(manager.close_all())
        await asyncio.wait_for(interrupted.wait(), 5)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert manager.has_pending_work and not await manager.list()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, 5)
        assert trees[0].process.returncode is not None
        assert not manager.has_pending_work and not await manager.list()
    finally:
        release.set()
        await manager.close_all()
        await asyncio.gather(call, return_exceptions=True)
        for tree in trees:
            if tree.process.returncode is None:
                await tree.terminate()
