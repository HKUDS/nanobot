from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.exec_session import (
    ExecSessionManager,
    ExecSessionTool,
    ListExecSessionsTool,
)
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.shell import ExecTool


def _python(code: str) -> list[str]:
    return [sys.executable, "-u", "-c", code]


def _session_id(output: str) -> str:
    match = re.search(r"session_id:\s*([0-9a-f]+)", output)
    assert match, output
    return match.group(1)


def _listed_ids(output: str) -> list[str]:
    return re.findall(r"^([0-9a-f]+)\s*\|", output, flags=re.MULTILINE)


def _exit_code(output: str) -> int:
    match = re.search(r"Exit code:\s*(-?\d+)", output)
    assert match, output
    return int(match.group(1))


def _silent_seconds(output: str) -> float:
    match = re.search(r"Output silent[^\n]*?(\d+(?:\.\d+)?)\s*(?:s\b|seconds?\b)", output)
    assert match, output
    return float(match.group(1))


def _elapsed_seconds(output: str) -> float:
    match = re.search(r"Elapsed:\s*(\d+(?:\.\d+)?)s", output)
    assert match, output
    return float(match.group(1))


async def _file_text(path: Path, *, timeout: float = 5) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and (text := path.read_text()):
            return text
        await asyncio.sleep(0.02)
    raise AssertionError(f"subprocess did not write {path} within {timeout}s")


def _pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            assert error == 87, f"OpenProcess({pid}) failed: {error}"
            return False
        try:
            status = kernel32.WaitForSingleObject(handle, 0)
            assert status in (0, 258), f"WaitForSingleObject({pid}) failed: {status}"
            return status == 258  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed grandchild can remain a zombie until its new parent reaps it.
    stat = Path(f"/proc/{pid}/stat")
    try:
        if stat.exists() and stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return False
    except (FileNotFoundError, ProcessLookupError):
        return False
    return True


@pytest.mark.parametrize("error", [FileNotFoundError, ProcessLookupError])
def test_pid_probe_handles_process_reaped_during_stat_read(monkeypatch, error) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "kill", lambda _pid, _signal: None)
    monkeypatch.setattr(Path, "exists", lambda _path: True)

    def reaped(_path):
        raise error("process reaped after existence check")

    monkeypatch.setattr(Path, "read_text", reaped)
    assert not _pid_running(12345)


async def _pid_stopped(pid: int, *, timeout: float = 6) -> None:
    deadline = time.monotonic() + timeout
    while _pid_running(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.03)
    assert not _pid_running(pid), f"subprocess {pid} is still running after {timeout}s"


async def _cleanup_pidfiles(*paths: Path) -> None:
    pids = [int(path.read_text()) for path in paths if path.exists() and path.read_text()]
    for pid in pids:
        if _pid_running(pid):
            with suppress(ProcessLookupError, OSError):
                os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
    for pid in pids:
        await _pid_stopped(pid, timeout=3)


def _waiting_tree(parent_pidfile: Path, child_pidfile: Path) -> str:
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(child_pidfile)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    return (
        "import os,subprocess,sys; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable, '-u', '-c', {child!r}]); "
        f"Path({str(parent_pidfile)!r}).write_text(str(os.getpid())); "
        "child.wait()"
    )


async def test_trusted_default_runtime_can_exceed_model_request_limit():
    manager = ExecSessionManager()
    tool = ExecTool(
        max_runtime=12, max_runtime_limit=1, idle_timeout=0, session_manager=manager,
    )
    try:
        result = await tool.execute(command=_python(
            "import time; time.sleep(1.2); print('trusted default completed')"
        ))

        assert not is_tool_error_result(result), result
        assert "trusted default completed" in result
        assert _exit_code(result) == 0
    finally:
        await manager.close_all()


async def test_wait_timeout_leaves_stdin_gated_work_alive(tmp_path):
    ready = tmp_path / "ready"
    done = tmp_path / "done"
    code = (
        "import sys; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text('ready'); "
        "print('waiting for input', flush=True); line=sys.stdin.readline().strip(); "
        f"Path({str(done)!r}).write_text(line); "
        "print('completed:' + line, flush=True)"
    )
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=12, max_runtime_limit=12,
        idle_timeout=1, session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)
    list_tool = ListExecSessionsTool(manager=manager)
    try:
        initial = await tool.execute(command=_python(code), yield_time_ms=0)
        sid = _session_id(initial)
        assert await _file_text(ready) == "ready"

        waited = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=200)

        assert not is_tool_error_result(waited), waited
        assert "Wait timed out after 0.2s; session remains active." in waited
        assert f"Process running. session_id: {sid}" in waited
        listing = await list_tool.execute()
        assert _listed_ids(listing) == [sid]
        assert "| running |" in listing

        final = await session_tool.execute(
            session_id=sid, input="finish after wait\n", until_exit=True, timeout_ms=5000,
        )
        assert not is_tool_error_result(final), final
        assert "completed:finish after wait" in final
        assert _exit_code(final) == 0
        assert done.read_text() == "finish after wait"
    finally:
        await manager.close_all()


async def test_default_idle_reporting_survives_unpolled_silence_and_reads(tmp_path):
    ready = tmp_path / "ready"
    done = tmp_path / "done"
    code = (
        "import sys; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text('ready'); "
        "line=sys.stdin.readline().strip(); "
        f"Path({str(done)!r}).write_text(line); print('silent work completed', flush=True)"
    )
    manager = ExecSessionManager(result_retention=1)
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=12, max_runtime_limit=12,
        idle_timeout=1, session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)
    list_tool = ListExecSessionsTool(manager=manager)
    try:
        initial = await tool.execute(command=_python(code), yield_time_ms=0)
        sid = _session_id(initial)
        assert await _file_text(ready) == "ready"
        await asyncio.sleep(1.25)

        first = await session_tool.execute(session_id=sid, timeout_ms=0)
        first_idle = _silent_seconds(first)
        assert first_idle >= 1
        assert f"Process running. session_id: {sid}" in first
        listing = await list_tool.execute()
        assert _listed_ids(listing) == [sid]
        assert "| running |" in listing
        await asyncio.sleep(0.35)
        second = await session_tool.execute(session_id=sid, timeout_ms=0)
        assert _silent_seconds(second) >= first_idle + 0.2
        assert f"Process running. session_id: {sid}" in second

        final = await session_tool.execute(
            session_id=sid, input="still alive\n", until_exit=True, timeout_ms=5000,
        )
        assert not is_tool_error_result(final), final
        assert "silent work completed" in final
        assert _exit_code(final) == 0
        assert done.read_text() == "still alive"
    finally:
        await manager.close_all()


async def test_partial_stdout_and_stderr_bytes_refresh_idle_without_log_reads(tmp_path):
    ready = tmp_path / "ready"
    stdout_gate = tmp_path / "emit-stdout"
    stderr_gate = tmp_path / "emit-stderr"
    finish_gate = tmp_path / "finish"
    stdout_ack = tmp_path / "stdout-written"
    stderr_ack = tmp_path / "stderr-written"
    done = tmp_path / "done"
    code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text('ready')\n"
        f"while not Path({str(stdout_gate)!r}).exists(): time.sleep(0.02)\n"
        "os.write(1, bytes([0xE2]))\n"
        f"Path({str(stdout_ack)!r}).write_text('stdout')\n"
        f"while not Path({str(stderr_gate)!r}).exists(): time.sleep(0.02)\n"
        "os.write(2, bytes([0xE2]))\n"
        f"Path({str(stderr_ack)!r}).write_text('stderr')\n"
        f"while not Path({str(finish_gate)!r}).exists(): time.sleep(0.02)\n"
        f"Path({str(done)!r}).write_text(Path({str(finish_gate)!r}).read_text())\n"
        "print('byte-gated complete', flush=True)\n"
    )
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=12, max_runtime_limit=12,
        idle_timeout=2, idle_action="report", session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)

    async def wait_for_output_activity(after: float) -> float:
        async with asyncio.timeout(5):
            while True:
                info, = await manager.list()
                assert info.session_id == sid
                assert info.returncode is None
                # This anchor stays fixed between bytes, even if observation is delayed.
                output_at = info.elapsed_s - info.idle_s
                if output_at > after:
                    return output_at
                await asyncio.sleep(0.02)

    try:
        initial = await tool.execute(command=_python(code), yield_time_ms=0)
        sid = _session_id(initial)
        assert await _file_text(ready) == "ready"
        stdout_gate.write_text("emit")
        assert await _file_text(stdout_ack) == "stdout"
        stdout_at = await wait_for_output_activity(0)

        stderr_gate.write_text("emit")
        assert await _file_text(stderr_ack) == "stderr"
        await wait_for_output_activity(stdout_at)

        finish_gate.write_text("finish")
        final = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=5000)
        assert not is_tool_error_result(final), final
        assert "byte-gated complete" in final
        assert _exit_code(final) == 0
        assert done.read_text() == "finish"
    finally:
        await manager.close_all()


async def test_idle_termination_stops_owned_tree_without_tool_activity(tmp_path):
    parent_pidfile = tmp_path / "parent.pid"
    child_pidfile = tmp_path / "child.pid"
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=12, max_runtime_limit=12,
        idle_timeout=2, idle_action="terminate", session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)
    try:
        initial = await tool.execute(
            command=_python(_waiting_tree(parent_pidfile, child_pidfile)), yield_time_ms=0,
        )
        sid = _session_id(initial)
        parent_pid = int(await _file_text(parent_pidfile))
        child_pid = int(await _file_text(child_pidfile))
        assert _pid_running(parent_pid)
        assert _pid_running(child_pid)

        # Observe OS process exit before making another tool or manager call.
        await _pid_stopped(parent_pid)
        await _pid_stopped(child_pid, timeout=3)
        final = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=3000)

        assert is_tool_error_result(final), final
        assert "idle_timeout" in final
        assert _exit_code(final) != 0
    finally:
        try:
            await manager.close_all()
        finally:
            await _cleanup_pidfiles(parent_pidfile, child_pidfile)


async def test_hard_budget_counts_down_despite_output_and_repeated_waits(tmp_path):
    pidfile = tmp_path / "process.pid"
    code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pidfile)!r}).write_text(str(os.getpid())); n=0\n"
        "while True:\n"
        " n+=1\n"
        " print('progress:' + str(n), flush=True)\n"
        " time.sleep(0.15)\n"
    )
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=3, max_runtime_limit=3,
        idle_timeout=1, idle_action="terminate", session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)
    try:
        initial = await tool.execute(command=_python(code), yield_time_ms=0)
        sid = _session_id(initial)
        pid = int(await _file_text(pidfile))
        before = (await manager.list())[0]

        first = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=900)
        second = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=900)

        for waited in (first, second):
            assert "Wait timed out after 0.9s; session remains active." in waited
            assert "progress:" in waited
        after = (await manager.list())[0]
        assert before.remaining_s is not None and after.remaining_s is not None
        assert after.remaining_s <= before.remaining_s - 1.4
        assert after.idle_s < 0.7
        assert _pid_running(pid)

        await _pid_stopped(pid, timeout=5)
        final = await session_tool.execute(session_id=sid, until_exit=True, timeout_ms=3000)
        assert is_tool_error_result(final), final
        assert "max_runtime" in final
        assert "progress:" in final
        assert _exit_code(final) != 0
        assert 2.5 <= _elapsed_seconds(final) <= 4.5
        progress_counts = re.findall(r"progress:(\d+)", initial + first + second + final)
        assert max(map(int, progress_counts)) >= 8
    finally:
        try:
            await manager.close_all()
        finally:
            await _cleanup_pidfiles(pidfile)


@pytest.mark.parametrize(
    ("early_root_exit", "stop_reason"),
    [
        pytest.param(False, "max_runtime", id="ordinary-root-hard-budget"),
        pytest.param(True, "max_runtime", id="early-root-hard-budget"),
        pytest.param(True, "owner_closed", id="early-root-owner-close"),
    ],
)
async def test_execution_stop_stops_pipe_inheriting_child_after_root_exits(
    tmp_path, monkeypatch, early_root_exit, stop_reason,
):
    parent_pidfile = tmp_path / "parent.pid"
    child_pidfile = tmp_path / "child.pid"
    release_root = tmp_path / "release-root"
    release_child = tmp_path / "release-child"
    delayed_effect = tmp_path / "delayed-effect"
    child_code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(child_pidfile)!r}).write_text(str(os.getpid()))\n"
        f"while not Path({str(release_child)!r}).exists(): time.sleep(0.02)\n"
        f"Path({str(delayed_effect)!r}).write_text('child escaped execution stop')\n"
    )
    parent_code = (
        "import os,subprocess,sys,time; from pathlib import Path; "
        f"Path({str(parent_pidfile)!r}).write_text(str(os.getpid())); "
        f"subprocess.Popen([sys.executable, '-u', '-c', {child_code!r}]); "
        "print('worker launched', flush=True)\n"
    )
    if not early_root_exit:
        parent_code += f"while not Path({str(release_root)!r}).exists(): time.sleep(0.02)\n"

    real_spawn = ExecTool._spawn
    spawn_returned = asyncio.Event()

    async def spawn_with_exit_order(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        if early_root_exit:
            # Root exit may precede spawn return; inherited pipes must remain intact.
            async with asyncio.timeout(5):
                while process.returncode is None:
                    await asyncio.sleep(0.005)
            assert process.returncode == 0
        else:
            assert process.returncode is None
        spawn_returned.set()
        return process

    monkeypatch.setattr(ExecTool, "_spawn", staticmethod(spawn_with_exit_order))
    owner = RequestContext(channel="cli", chat_id="pipe-budget", session_key="cli:pipe-budget")
    manager = ExecSessionManager()
    max_runtime = 12 if stop_reason == "owner_closed" else 2
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=max_runtime, max_runtime_limit=max_runtime,
        idle_timeout=1, session_manager=manager,
    )
    initial_exec_task = None
    try:
        with request_context(owner):
            initial_exec_task = asyncio.create_task(tool.execute(command=_python(parent_code)))
        await asyncio.wait_for(spawn_returned.wait(), timeout=5)
        parent_pid = int(await _file_text(parent_pidfile))
        child_pid = int(await _file_text(child_pidfile))
        release_root.write_text("root may exit")
        await _pid_stopped(parent_pid, timeout=1)
        assert _pid_running(child_pid)
        assert not initial_exec_task.done()

        if stop_reason == "owner_closed":
            assert await asyncio.wait_for(
                manager.terminate_by_owner(owner.session_key), timeout=6,
            ) == 1
        await _pid_stopped(child_pid, timeout=5)
        release_child.write_text("perform the delayed write")
        final = await asyncio.wait_for(initial_exec_task, timeout=3)

        if stop_reason == "max_runtime":
            assert is_tool_error_result(final), final
            assert "Reason: max_runtime." in final
            assert 1.5 <= _elapsed_seconds(final) <= 3.5
        else:
            assert not is_tool_error_result(final), final
            assert "Session terminated. Reason: owner_closed." in final
        assert "worker launched" in final
        assert _exit_code(final) == 0  # Only the root exited successfully.
        assert not delayed_effect.exists()
        assert await manager.list(owner_session_key=owner.session_key) == []
    finally:
        try:
            await _cleanup_pidfiles(parent_pidfile, child_pidfile)
        finally:
            try:
                await asyncio.wait_for(manager.close_all(), timeout=6)
            finally:
                if initial_exec_task is not None:
                    initial_exec_task.cancel()
                    await asyncio.gather(initial_exec_task, return_exceptions=True)


async def test_inline_work_reports_silence_then_hits_same_fixed_hard_budget(tmp_path):
    pidfile = tmp_path / "process.pid"
    gate = tmp_path / "emit-output"
    ticks = tmp_path / "ticks"
    code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
        f"while not Path({str(gate)!r}).exists(): time.sleep(0.02)\n"
        "n=0\n"
        "while True:\n"
        " n+=1\n"
        " print('inline-progress:' + str(n), flush=True)\n"
        f" Path({str(ticks)!r}).write_text(str(n))\n"
        " time.sleep(0.15)\n"
    )
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=4, max_runtime_limit=4,
        idle_timeout=1, session_manager=manager,
    )
    list_tool = ListExecSessionsTool(manager=manager)
    inline_task = None
    try:
        inline_task = asyncio.create_task(tool.execute(command=_python(code)))
        pid = int(await _file_text(pidfile))
        await asyncio.sleep(1.25)

        listing = await list_tool.execute()
        assert len(_listed_ids(listing)) == 1, listing
        assert "| running |" in listing
        assert (await manager.list())[0].idle_s >= 1
        assert not inline_task.done()
        assert _pid_running(pid)

        gate.write_text("emit")
        assert int(await _file_text(ticks)) >= 1
        await _pid_stopped(pid)
        final = await asyncio.wait_for(inline_task, timeout=3)

        assert is_tool_error_result(final), final
        assert "inline-progress:" in final
        assert "max_runtime" in final
        assert _exit_code(final) != 0
        assert 3.5 <= _elapsed_seconds(final) <= 5.5
        assert await list_tool.execute() == "No active exec sessions."
    finally:
        try:
            await manager.close_all()
        finally:
            if inline_task is not None:
                inline_task.cancel()
                await asyncio.gather(inline_task, return_exceptions=True)
            await _cleanup_pidfiles(pidfile)


async def test_owner_close_stops_inline_tree_and_preserves_other_owner_work(tmp_path):
    parent_pidfile = tmp_path / "owner-a-parent.pid"
    child_pidfile = tmp_path / "owner-a-child.pid"
    survivor_pidfile = tmp_path / "owner-b.pid"
    done = tmp_path / "owner-b-done"
    survivor_code = (
        "import os,sys; from pathlib import Path; "
        f"Path({str(survivor_pidfile)!r}).write_text(str(os.getpid())); "
        "print('owner-b-ready', flush=True); line=sys.stdin.readline().strip(); "
        f"Path({str(done)!r}).write_text(line); print('owner-b-completed', flush=True)"
    )
    owner_a = RequestContext(channel="cli", chat_id="budget-a", session_key="cli:budget-a")
    owner_b = RequestContext(channel="cli", chat_id="budget-b", session_key="cli:budget-b")
    manager = ExecSessionManager()
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=12, max_runtime_limit=12,
        idle_timeout=1, session_manager=manager,
    )
    session_tool = ExecSessionTool(manager=manager)
    list_tool = ListExecSessionsTool(manager=manager)
    inline_task = None
    try:
        with request_context(owner_a):
            inline_task = asyncio.create_task(tool.execute(
                command=_python(_waiting_tree(parent_pidfile, child_pidfile)),
            ))
            parent_pid = int(await _file_text(parent_pidfile))
            child_pid = int(await _file_text(child_pidfile))
            owner_listing = await list_tool.execute()
            owner_ids = _listed_ids(owner_listing)
            assert len(owner_ids) == 1, owner_listing
            sid_a = owner_ids[0]

        with request_context(owner_b):
            initial_b = await tool.execute(command=_python(survivor_code), yield_time_ms=0)
            sid_b = _session_id(initial_b)
            survivor_pid = int(await _file_text(survivor_pidfile))
            assert _listed_ids(await list_tool.execute()) == [sid_b]
            denied = await session_tool.execute(session_id=sid_a, terminate=True)
            assert is_tool_error_result(denied), denied
            assert denied == f"Error: exec session not found: {sid_a!r}"

        assert _pid_running(parent_pid)
        assert _pid_running(child_pid)
        assert await manager.terminate_by_owner("cli:budget-a") == 1
        await _pid_stopped(parent_pid, timeout=3)
        await _pid_stopped(child_pid, timeout=3)
        final_a = await asyncio.wait_for(inline_task, timeout=3)
        assert "Session terminated." in final_a
        assert _exit_code(final_a) != 0

        with request_context(owner_b):
            assert _pid_running(survivor_pid)
            listing = await list_tool.execute()
            assert _listed_ids(listing) == [sid_b]
            assert "| running |" in listing
            final_b = await session_tool.execute(
                session_id=sid_b, input="owner-b-success\n", until_exit=True, timeout_ms=5000,
            )
            assert not is_tool_error_result(final_b), final_b
            assert "owner-b-completed" in final_b
            assert _exit_code(final_b) == 0
            assert done.read_text() == "owner-b-success"
    finally:
        try:
            await manager.close_all()
        finally:
            if inline_task is not None:
                inline_task.cancel()
                await asyncio.gather(inline_task, return_exceptions=True)
            await _cleanup_pidfiles(parent_pidfile, child_pidfile, survivor_pidfile)
