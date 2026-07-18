from __future__ import annotations

import asyncio
import base64
import re
import shlex
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent import context as agent_context
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.exec_session import (
    ExecSessionManager,
    ListExecSessionsTool,
    WriteStdinTool,
)
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.shell import ExecTool


def _python_command(code: str) -> str:
    if sys.platform == "win32":
        return f"{subprocess.list2cmdline([sys.executable])} -u -c {subprocess.list2cmdline([code])}"
    return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"


def _waiting_shell_command(initial: str, *, delayed: str | None = None) -> str:
    """Print deterministic output, then wait in the shell itself for stdin.

    Long-lived Python children keep inherited pipes open after their parent
    shell is terminated on Windows. These tests exercise exec-session control,
    not process-tree semantics, so keep the waiter in the managed shell.
    """
    if sys.platform == "win32":
        def quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        parts = [f"Write-Output {quote(initial)}"]
        if delayed is not None:
            parts.extend(("Start-Sleep -Milliseconds 100", f"Write-Output {quote(delayed)}"))
        parts.append("$null = [Console]::In.ReadLine()")
        return "; ".join(parts)

    parts = [f"printf '%s\\n' {shlex.quote(initial)}"]
    if delayed is not None:
        parts.extend(("sleep 0.1", f"printf '%s\\n' {shlex.quote(delayed)}"))
    parts.append("IFS= read -r _")
    return "; ".join(parts)


def _session_id(output: str) -> str:
    match = re.search(r"session_id:\s*([0-9a-f]+)", output)
    assert match, output
    return match.group(1)


def test_exec_keeps_one_shot_behavior_without_yield_time_ms(tmp_path):
    async def run() -> str:
        tool = ExecTool(working_dir=str(tmp_path), timeout=5)
        return await tool.execute(command="echo hello")

    result = asyncio.run(run())

    assert "hello" in result
    assert "Exit code: 0" in result
    assert "session_id:" not in result


def test_exec_accepts_command_aliases(tmp_path):
    async def run() -> str:
        tool = ExecTool(working_dir="/")
        return await tool.execute(
            cmd=_python_command("import os; print(os.getcwd())"),
            workdir=str(tmp_path),
        )

    result = asyncio.run(run())

    assert str(tmp_path) in result
    assert "Exit code: 0" in result


def test_exec_returns_completed_session_output_when_yield_time_ms_is_used(tmp_path):
    async def run() -> str:
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)

        result = await tool.execute(command="echo hello", yield_time_ms=1000)
        if "session_id:" in result:
            sid = _session_id(result)
            result += "\n" + await stdin_tool.execute(
                session_id=sid,
                chars="",
                yield_time_ms=1000,
            )
        return result

    result = asyncio.run(run())

    assert "hello" in result
    assert "Exit code: 0" in result
    assert "session_id:" not in result


def test_exec_session_yield_returns_when_process_finishes_early(tmp_path):
    async def run() -> tuple[str, float]:
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        command = _python_command("import time; time.sleep(0.1); print('done')")
        started = time.monotonic()
        result = await tool.execute(command=command, yield_time_ms=1200)
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(run())

    assert "done" in result
    assert "Exit code: 0" in result
    assert "session_id:" not in result
    assert elapsed < 1.0


def test_exec_session_accepts_max_output_tokens_alias(tmp_path):
    async def run() -> str:
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        command = _python_command("print('A' * 2000)")
        return await tool.execute(
            command=command,
            yield_time_ms=1000,
            max_output_tokens=1000,
        )

    result = asyncio.run(run())

    assert "chars truncated" in result
    assert "Exit code: 0" in result


def test_exec_one_shot_accepts_max_output_tokens_alias(tmp_path):
    async def run() -> str:
        tool = ExecTool(working_dir=str(tmp_path), timeout=5)
        command = _python_command("print('A' * 2000)")
        return await tool.execute(command=command, max_output_tokens=1000)

    result = asyncio.run(run())

    assert "chars truncated" in result
    assert "Exit code: 0" in result


def test_exec_accepts_supported_shell_parameter(tmp_path):
    async def run() -> str:
        tool = ExecTool(working_dir=str(tmp_path), timeout=5)
        return await tool.execute(command="echo shell-ok", shell="sh", login=False)

    if sys.platform == "win32":
        return
    result = asyncio.run(run())

    assert "shell-ok" in result
    assert "Exit code: 0" in result


def test_exec_rejects_unsupported_shell(tmp_path):
    async def run() -> str:
        tool = ExecTool(working_dir=str(tmp_path), timeout=5)
        return await tool.execute(command="echo no", shell="python")

    if sys.platform == "win32":
        return
    result = asyncio.run(run())

    assert "unsupported shell" in result


def test_exec_can_continue_with_stdin(tmp_path):
    async def run() -> tuple[str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _python_command(
            "import sys; print('ready', flush=True); "
            "line=sys.stdin.readline(); print('got:' + line.strip(), flush=True)"
        )

        initial = await exec_tool.execute(command=command, yield_time_ms=500)
        sid = _session_id(initial)
        result = await stdin_tool.execute(session_id=sid, chars="ping\n", yield_time_ms=1000)
        return initial, result

    initial, result = asyncio.run(run())
    assert "ready" in initial + result
    assert "Process running" in initial
    assert "Elapsed:" in initial
    assert "got:ping" in result
    assert "Exit code: 0" in result
    assert "Elapsed:" in result


def test_write_stdin_can_close_stdin(tmp_path):
    async def run() -> tuple[str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _python_command(
            "import sys; print('ready', flush=True); "
            "data=sys.stdin.read(); print('got:' + data, flush=True)"
        )

        initial = await exec_tool.execute(command=command, yield_time_ms=1500)
        sid = _session_id(initial)
        result = await stdin_tool.execute(
            session_id=sid,
            chars="payload",
            close_stdin=True,
            yield_time_ms=1500,
        )
        return initial, result

    initial, result = asyncio.run(run())
    assert "ready" in initial + result
    assert "got:payload" in result
    assert "Stdin closed." in result
    assert "Exit code: 0" in result


def test_write_stdin_can_terminate_session(tmp_path):
    async def run() -> tuple[str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=30, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _waiting_shell_command("ready")

        initial = await exec_tool.execute(command=command, yield_time_ms=100)
        sid = _session_id(initial)
        waited = await stdin_tool.execute(
            session_id=sid,
            wait_for="ready",
            wait_timeout_ms=10000,
            yield_time_ms=0,
        )
        result = await stdin_tool.execute(
            session_id=sid,
            terminate=True,
            yield_time_ms=0,
        )
        return initial + waited, result

    initial, result = asyncio.run(run())
    assert "ready" in initial
    assert "Session terminated." in result
    assert "Exit code:" in result


def test_write_stdin_accepts_max_output_tokens_alias(tmp_path):
    async def run() -> tuple[str, str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _waiting_shell_command("A" * 2000)

        initial = await exec_tool.execute(command=command, yield_time_ms=0)
        sid = _session_id(initial)
        poll = await stdin_tool.execute(
            session_id=sid,
            yield_time_ms=500,
            max_output_tokens=1000,
        )
        cleanup = await stdin_tool.execute(session_id=sid, terminate=True, yield_time_ms=0)
        return initial, poll, cleanup

    initial, poll, cleanup = asyncio.run(run())
    assert "Process running" in initial
    assert "chars truncated" in poll
    assert "Session terminated." in cleanup


def test_write_stdin_preserves_completed_session_output_until_polled(tmp_path):
    async def run() -> tuple[str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _python_command(
            "import time; print('ready', flush=True); "
            "time.sleep(0.1); print('done', flush=True)"
        )

        initial = await exec_tool.execute(command=command, yield_time_ms=50)
        sid = _session_id(initial)
        await asyncio.wait_for(manager._sessions[sid].process.wait(), timeout=2)
        final = await stdin_tool.execute(session_id=sid, chars="", yield_time_ms=0)
        return initial, final

    initial, final = asyncio.run(run())

    assert "ready" in initial + final
    assert "done" in final
    assert "Exit code: 0" in final


def test_write_stdin_can_wait_for_expected_output(tmp_path):
    async def run() -> tuple[str, str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _waiting_shell_command("booting", delayed="ready")

        initial = await exec_tool.execute(command=command, yield_time_ms=100)
        sid = _session_id(initial)
        waited = await stdin_tool.execute(
            session_id=sid,
            wait_for="ready",
            wait_timeout_ms=1000,
            yield_time_ms=0,
        )
        cleanup = await stdin_tool.execute(session_id=sid, terminate=True, yield_time_ms=0)
        return initial, waited, cleanup

    initial, waited, cleanup = asyncio.run(run())

    assert "Process running" in initial
    assert "booting" in initial + waited
    assert "ready" in waited
    assert "Wait target not observed" not in waited
    assert "Session terminated." in cleanup


def test_write_stdin_wait_for_reports_timeout_without_killing_session(tmp_path):
    async def run() -> tuple[str, str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _waiting_shell_command("booting")

        initial = await exec_tool.execute(command=command, yield_time_ms=100)
        sid = _session_id(initial)
        waited = await stdin_tool.execute(
            session_id=sid,
            wait_for="never-ready",
            wait_timeout_ms=200,
            yield_time_ms=0,
        )
        cleanup = await stdin_tool.execute(session_id=sid, terminate=True, yield_time_ms=0)
        return initial, waited, cleanup

    initial, waited, cleanup = asyncio.run(run())

    assert "Process running" in initial
    assert "booting" in initial + waited
    assert "Process running" in waited
    assert "Wait target not observed: 'never-ready'" in waited
    assert "Session terminated." in cleanup


def test_exec_session_mode_reuses_exec_safety_guard(tmp_path):
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path),
        deny_patterns=[r"echo\s+blocked"],
        session_manager=manager,
    )

    result = asyncio.run(tool.execute(command="echo blocked", yield_time_ms=0))

    assert "blocked by deny pattern" in result


def test_write_stdin_reports_missing_session(tmp_path):
    manager = ExecSessionManager()
    tool = WriteStdinTool(manager=manager)

    result = asyncio.run(tool.execute(session_id="missing\nExit code: 0", chars=""))

    assert result == "Error: exec session not found: 'missing\\nExit code: 0'"
    assert is_tool_error_result("write_stdin", result)


def test_list_exec_sessions_reports_running_commands(tmp_path):
    async def run() -> tuple[str, str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        list_tool = ListExecSessionsTool(manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _waiting_shell_command("ready")

        initial = await exec_tool.execute(command=command, yield_time_ms=500)
        sid = _session_id(initial)
        listing = await list_tool.execute()
        cleanup = await stdin_tool.execute(session_id=sid, terminate=True, yield_time_ms=0)
        return sid, listing, cleanup

    sid, listing, cleanup = asyncio.run(run())

    assert sid in listing
    assert "running" in listing
    assert "elapsed=" in listing
    assert "remaining=" in listing
    assert str(tmp_path) in listing
    assert "Session terminated." in cleanup


def test_exec_sessions_are_scoped_to_request_session_key(tmp_path):
    async def run() -> tuple[str, str, str, str, str, str]:
        manager = ExecSessionManager()
        exec_tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        list_tool = ListExecSessionsTool(manager=manager)
        stdin_tool = WriteStdinTool(manager=manager)
        command = _python_command(
            "import time; print('ready', flush=True); time.sleep(5)"
        )

        token_a = bind_request_context(
            RequestContext(channel="cli", chat_id="a", session_key="cli:a")
        )
        try:
            initial = await exec_tool.execute(command=command, yield_time_ms=100)
            sid = _session_id(initial)
            owner_listing = await list_tool.execute()
        finally:
            reset_request_context(token_a)

        unbound_listing = await list_tool.execute()

        token_b = bind_request_context(
            RequestContext(channel="cli", chat_id="b", session_key="cli:b")
        )
        try:
            other_listing = await list_tool.execute()
            other_write = await stdin_tool.execute(session_id=sid, yield_time_ms=0)
        finally:
            reset_request_context(token_b)

        token_a = bind_request_context(
            RequestContext(channel="cli", chat_id="a", session_key="cli:a")
        )
        try:
            cleanup = await stdin_tool.execute(session_id=sid, terminate=True, yield_time_ms=0)
        finally:
            reset_request_context(token_a)

        return sid, owner_listing, unbound_listing, other_listing, other_write, cleanup

    sid, owner_listing, unbound_listing, other_listing, other_write, cleanup = asyncio.run(run())

    assert sid in owner_listing
    assert unbound_listing == "No active exec sessions."
    assert other_listing == "No active exec sessions."
    assert other_write == f"Error: exec session not found: {sid!r}"
    assert "Session terminated." in cleanup


def test_list_exec_sessions_reports_empty_state():
    result = asyncio.run(ListExecSessionsTool(manager=ExecSessionManager()).execute())

    assert result == "No active exec sessions."


def test_exec_session_manager_close_all_terminates_active_sessions(tmp_path):
    async def run() -> None:
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=30, session_manager=manager)
        initial = await tool.execute(
            command=_waiting_shell_command("ready"),
            yield_time_ms=100,
        )
        sid = _session_id(initial)
        process = manager._sessions[sid].process
        assert process.returncode is None

        closed = await manager.close_all()

        assert closed == 1
        assert process.returncode is not None
        assert manager._sessions == {}
        assert await manager.close_all() == 0

    asyncio.run(run())


def test_exec_session_manager_shutdown_terminates_child_processes(tmp_path):
    async def run() -> None:
        marker = tmp_path / "orphaned-child.txt"
        child_code = (
            "import pathlib,time; time.sleep(2); "
            f"pathlib.Path({str(marker)!r}).write_text('alive')"
        )
        child_payload = base64.b64encode(child_code.encode()).decode()
        parent_code = (
            "import base64,subprocess,sys,time; "
            f"child=base64.b64decode('{child_payload}').decode(); "
            "subprocess.Popen([sys.executable, '-c', child]); "
            "print('ready', flush=True); time.sleep(4)"
        )
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=30, session_manager=manager)
        initial = await tool.execute(command=_python_command(parent_code), yield_time_ms=500)
        assert "ready" in initial
        assert "Process running" in initial

        await manager.close_all()
        await asyncio.sleep(2.3)

        assert not marker.exists()

    asyncio.run(run())


def test_exec_session_manager_rejects_new_sessions_after_shutdown(tmp_path):
    async def run() -> str:
        manager = ExecSessionManager()
        await manager.close_all()
        tool = ExecTool(working_dir=str(tmp_path), timeout=5, session_manager=manager)
        return await tool.execute(command="echo should-not-run", yield_time_ms=0)

    result = asyncio.run(run())

    assert result == "Error executing command: exec session manager is closed"


def test_exec_session_manager_retains_and_aggregates_failed_cleanup():
    async def run() -> None:
        manager = ExecSessionManager()
        first = SimpleNamespace(
            session_id="first",
            kill=AsyncMock(side_effect=OSError("first failed")),
        )
        second = SimpleNamespace(
            session_id="second",
            kill=AsyncMock(side_effect=RuntimeError("second failed")),
        )
        manager._sessions = {first.session_id: first, second.session_id: second}

        with pytest.raises(ExceptionGroup) as exc_info:
            await manager.close_all()

        assert len(exc_info.value.exceptions) == 2
        assert manager._sessions == {first.session_id: first, second.session_id: second}
        first.kill.assert_awaited_once()
        second.kill.assert_awaited_once()

        first.kill.side_effect = None
        second.kill.side_effect = None
        assert await manager.close_all() == 2
        assert manager._sessions == {}

    asyncio.run(run())


def test_exec_session_manager_preserves_single_cleanup_error():
    async def run() -> None:
        manager = ExecSessionManager()
        session = SimpleNamespace(
            session_id="failed",
            kill=AsyncMock(side_effect=OSError("cleanup failed")),
        )
        manager._sessions = {session.session_id: session}

        with pytest.raises(OSError, match="cleanup failed"):
            await manager.close_all()

        assert manager._sessions == {session.session_id: session}

    asyncio.run(run())


def test_agent_loop_shutdown_closes_exec_sessions(tmp_path, monkeypatch):
    async def run() -> None:
        manager = ExecSessionManager()
        tool = ExecTool(working_dir=str(tmp_path), timeout=30, session_manager=manager)
        initial = await tool.execute(
            command=_waiting_shell_command("ready"),
            yield_time_ms=100,
        )
        sid = _session_id(initial)
        process = manager._sessions[sid].process

        monkeypatch.setattr(agent_context, "close_mcp", lambda _state: asyncio.sleep(0))
        loop = object.__new__(AgentLoop)
        loop._background_tasks = []
        loop._exec_session_manager = manager
        loop.subagents = SimpleNamespace(close=AsyncMock())

        await loop.close_mcp()
        await loop.close_mcp()

        assert process.returncode is not None
        assert manager._sessions == {}
        assert loop.subagents.close.await_count == 2

    asyncio.run(run())


def test_agent_loop_shutdown_attempts_all_cleanup_after_errors(monkeypatch):
    async def run() -> None:
        loop = object.__new__(AgentLoop)
        loop._background_tasks = []
        loop.subagents = SimpleNamespace(
            close=AsyncMock(side_effect=RuntimeError("subagent cleanup failed")),
        )
        loop._exec_session_manager = SimpleNamespace(
            close_all=AsyncMock(side_effect=OSError("exec cleanup failed")),
        )
        close_mcp = AsyncMock()
        monkeypatch.setattr(agent_context, "close_mcp", close_mcp)

        with pytest.raises(BaseExceptionGroup) as exc_info:
            await loop.close_mcp()

        assert len(exc_info.value.exceptions) == 2
        loop.subagents.close.assert_awaited_once()
        loop._exec_session_manager.close_all.assert_awaited_once()
        close_mcp.assert_awaited_once_with(loop)

    asyncio.run(run())


def test_agent_loop_shutdown_preserves_single_cleanup_error(monkeypatch):
    async def run() -> None:
        loop = object.__new__(AgentLoop)
        loop._background_tasks = []
        loop.subagents = SimpleNamespace(
            close=AsyncMock(side_effect=RuntimeError("subagent cleanup failed")),
        )
        loop._exec_session_manager = SimpleNamespace(close_all=AsyncMock())
        close_mcp = AsyncMock()
        monkeypatch.setattr(agent_context, "close_mcp", close_mcp)

        with pytest.raises(RuntimeError, match="subagent cleanup failed"):
            await loop.close_mcp()

        loop._exec_session_manager.close_all.assert_awaited_once()
        close_mcp.assert_awaited_once_with(loop)

    asyncio.run(run())
