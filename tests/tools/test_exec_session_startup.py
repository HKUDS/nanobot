from __future__ import annotations

import asyncio
import sys

import pytest

from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.shell import ExecTool


async def test_owner_cancellation_during_startup_preserves_other_execution(tmp_path, monkeypatch):
    manager = ExecSessionManager(max_sessions=2)
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    blocked_command = [sys.executable, "-u", "-c", "print('blocked launch')"]
    entered = asyncio.Event()
    release = asyncio.Event()
    spawn = manager._spawn

    async def gated_spawn(command, cwd, env, shell_program, login, *, stdin):
        if command == blocked_command:
            entered.set()
            await release.wait()
        return await spawn(command, cwd, env, shell_program, login, stdin=stdin)

    monkeypatch.setattr(manager, "_spawn", gated_spawn)
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
