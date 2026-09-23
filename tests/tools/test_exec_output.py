import asyncio
import os
import shlex
import sys
import time
from unittest.mock import Mock

import pytest

from nanobot.agent.tools.exec_output import ExecOutputLog
from nanobot.agent.tools.exec_session import ExecSessionManager


def _waiting_shell_command(text, *, delayed=None):
    if sys.platform == "win32":
        def quote(value):
            return "'" + value.replace("'", "''") + "'"
        parts = [f"Write-Output {quote(text)}"]
        if delayed:
            parts.extend(("$null = [Console]::In.ReadLine()", f"Write-Output {quote(delayed)}"))
        return "; ".join([*parts, "$null = [Console]::In.ReadLine()"])
    parts = [f"printf '%s\\n' {shlex.quote(text)}"]
    if delayed:
        parts.extend(("IFS= read -r _", f"printf '%s\\n' {shlex.quote(delayed)}"))
    return "; ".join([*parts, "IFS= read -r _"])


def test_tail_cursor_is_repeatable_bounded_and_reports_loss():
    output = ExecOutputLog(max_chars=8, max_chunks=2)
    output.append("1234", "stdout")
    first = output.read()
    assert first == output.read()
    output.append("err", "stderr")
    assert output.read(first["cursor"])["chunks"] == [{"seq": 2, "stream": "stderr", "text": "err"}]
    output.append("abcdefghij", "stdout")
    assert output.read()["chunks"] == [{"seq": 3, "stream": "stdout", "text": "cdefghij"}]
    assert output.read()["omitted_chars"] == 9
    assert output.read(1)["reset"]
    assert output.read(99)["reset"]
    output.read()["chunks"][0]["text"] = "mutated"
    assert output.read()["chunks"][0]["text"] == "cdefghij"
    output.clear()
    assert output.read()["chunks"] == []
    with pytest.raises(ValueError):
        ExecOutputLog(max_chars=0)


async def test_completed_count_and_timer_expiry_forget_without_another_read():
    manager = ExecSessionManager()
    entries = [Mock(session_id=f"{n:012x}", retains_output=True) for n in range(35)]
    for session in entries:
        manager._retain_completed(session)
    assert len(manager._completed) == len(manager._expiry) == 32
    for old in entries[:3]:
        old.forget_output.assert_called_once()
    sid = entries[3].session_id
    handle = manager._expiry[sid]
    manager._expire_completed(sid)
    assert handle.cancelled() and sid not in manager._completed
    entries[3].forget_output.assert_called_once()
    await manager.close_all()
    assert not manager._expiry and not manager._completed


async def start(manager, tmp_path, owner="websocket:a", text="first", delayed=None):
    return await manager.start(command=_waiting_shell_command(text, delayed=delayed), cwd=str(tmp_path),
        env=os.environ.copy(), timeout=30, shell_program=None, login=False,
        yield_time_ms=1000, max_output_chars=10000, owner_session_key=owner)


async def test_ui_read_does_not_consume_agent_output_or_extend_idle_life(tmp_path):
    manager = ExecSessionManager()
    try:
        sid, initial = await start(manager, tmp_path, delayed="second")
        assert "first" in initial.output
        session = manager._sessions[sid]
        accessed = session.last_access
        first = await manager.inspect_output("websocket:a", sid)
        assert "first" in "".join(c["text"] for c in first["chunks"])
        await session.write("\n")
        for _ in range(100):
            detail = await manager.inspect_output("websocket:a", sid)
            if "second" in "".join(c["text"] for c in detail["chunks"]):
                break
            await asyncio.sleep(0.02)
        assert "second" in "".join(c["text"] for c in detail["chunks"])
        assert session.last_access == accessed
        assert (await manager.inspect_output("websocket:a", sid))["chunks"] == detail["chunks"]
        agent = await manager.write(session_id=sid, chars=None, close_stdin=False, terminate=False,
            yield_time_ms=0, max_output_chars=10000, owner_session_key="websocket:a")
        assert "second" in agent.output and "first" not in agent.output
        assert "second" in "".join(c["text"] for c in (await manager.inspect_output("websocket:a", sid))["chunks"])
    finally:
        await manager.close_all()


async def test_stop_is_scoped_idempotent_and_preserves_final_agent_poll(tmp_path):
    manager = ExecSessionManager()
    try:
        sid, _ = await start(manager, tmp_path)
        sibling, _ = await start(manager, tmp_path)
        other, _ = await start(manager, tmp_path, owner="websocket:b")
        assert len(await manager.inspect_commands("websocket:a")) == 2
        with pytest.raises(KeyError):
            await manager.inspect_output("websocket:b", sid, stop=True)
        stopped = await manager.inspect_output("websocket:a", sid, stop=True)
        assert stopped["state"] == "stopped"
        assert (await manager.inspect_output("websocket:a", sid, stop=True))["state"] == "stopped"
        assert (await manager.inspect_output("websocket:a", sibling))["state"] == "running"
        assert (await manager.inspect_output("websocket:b", other))["state"] == "running"
        poll = await manager.write(session_id=sid, chars=None, close_stdin=False, terminate=False,
            yield_time_ms=0, max_output_chars=10000, owner_session_key="websocket:a")
        assert poll.done and poll.terminated
        assert (await manager.inspect_output("websocket:a", sid))["chunks"] == stopped["chunks"]
        await manager.terminate_by_owner("websocket:a")
        assert await manager.inspect_commands("websocket:a") == []
        with pytest.raises(KeyError):
            await manager.inspect_output("websocket:a", sid)
    finally:
        await manager.close_all()


async def test_completed_retention_is_bounded_and_shutdown_forgets(tmp_path):
    manager = ExecSessionManager()
    try:
        sid, _ = await start(manager, tmp_path)
        session = manager._sessions[sid]
        await manager.write(session_id=sid, chars=None, close_stdin=False, terminate=True,
            yield_time_ms=0, max_output_chars=10000, owner_session_key="websocket:a")
        assert len(await manager.inspect_commands("websocket:a")) == 1
        manager._completed[sid] = (time.monotonic() - 1801, session)
        assert await manager.inspect_commands("websocket:a") == []
        assert not session.retains_output
        # Late readers/updates cannot republish forgotten private output.
        with pytest.raises(KeyError):
            await session.inspect()
    finally:
        await manager.close_all()
    assert await manager.inspect_commands("websocket:a") == []
    assert await ExecSessionManager().inspect_commands("websocket:a") == []
