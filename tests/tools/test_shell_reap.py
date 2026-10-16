"""Tests for subprocess zombie reaping in ExecTool / exec sessions."""

from __future__ import annotations

import asyncio
import base64
import shlex
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool, _ExecSession
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.shell import ExecTool, _reap_pid


def _python_command(code: str) -> str:
    if sys.platform == "win32":
        return f"{subprocess.list2cmdline([sys.executable])} -u -c {subprocess.list2cmdline([code])}"
    return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"


class _MockProcess:
    def __init__(
        self, *, pid: int, returncode: int | None, stdout: bytes = b"", stderr: bytes = b"",
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self.stdin = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        self.exited = asyncio.Event()
        self._exit_code = returncode
        self.kill = MagicMock(side_effect=lambda: self.exit(-9))
        self.wait = AsyncMock(side_effect=self._wait)
        if returncode is not None:
            self.exit(returncode)

    def exit(self, returncode: int, *, close_streams: bool = True) -> None:
        self._exit_code = returncode
        if close_streams:
            self.stdout.feed_eof()
            self.stderr.feed_eof()
        self.exited.set()

    async def _wait(self) -> int:
        await self.exited.wait()
        assert self._exit_code is not None
        self.returncode = self._exit_code
        return self.returncode


async def _cleanup_session(session: _ExecSession) -> None:
    await asyncio.wait_for(session.kill(), timeout=5)
    tasks = (
        session._stdout_task, session._stderr_task, session._completion_task,
        session._timeout_task, session._kill_task,
    )
    await asyncio.wait_for(
        asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True),
        timeout=5,
    )


def test_reap_pid_noops_without_waitpid():
    """On platforms (or test stubs) without waitpid, reaping is a no-op."""
    with patch("nanobot.agent.tools.shell.os") as mock_os:
        mock_os.waitpid = None
        mock_os.WNOHANG = None
        _reap_pid(12345)


def test_reap_pid_calls_waitpid_wnohang():
    with patch("nanobot.agent.tools.shell.os") as mock_os:
        mock_os.waitpid = MagicMock(return_value=(12345, 0))
        mock_os.WNOHANG = 1
        _reap_pid(12345)
        mock_os.waitpid.assert_called_once_with(12345, 1)


def test_reap_pid_swallows_already_reaped_errors():
    with patch("nanobot.agent.tools.shell.os") as mock_os:
        mock_os.WNOHANG = 1
        mock_os.waitpid = MagicMock(side_effect=ChildProcessError("no child"))
        _reap_pid(99)

        mock_os.waitpid = MagicMock(side_effect=ProcessLookupError("gone"))
        _reap_pid(99)


@pytest.mark.asyncio
async def test_kill_process_skips_kill_when_already_exited():
    """Already-dead processes must not raise ProcessLookupError from kill()."""
    process = _MockProcess(pid=4242, returncode=0)
    process.kill = MagicMock(side_effect=ProcessLookupError("already dead"))

    with patch("nanobot.agent.tools.shell._reap_pid") as reap:
        await ExecTool._kill_process(process)

    process.kill.assert_not_called()
    process.wait.assert_not_called()
    reap.assert_called_once_with(4242)


@pytest.mark.asyncio
async def test_kill_process_kills_and_reaps_live_process():
    process = _MockProcess(pid=77, returncode=None)

    with patch("nanobot.agent.tools.shell._reap_pid") as reap:
        await ExecTool._kill_process(process)

    process.kill.assert_called_once()
    process.wait.assert_awaited()
    assert process.returncode == -9
    reap.assert_called_once_with(77)


@pytest.mark.asyncio
async def test_kill_process_reaps_even_if_kill_races_exit():
    """If the child exits between returncode check and kill(), still reap."""
    process = _MockProcess(pid=88, returncode=None)

    def raced_exit() -> None:
        process.exit(0)
        raise ProcessLookupError("raced exit")

    process.kill.side_effect = raced_exit

    with patch("nanobot.agent.tools.shell._reap_pid") as reap:
        await ExecTool._kill_process(process)

    process.kill.assert_called_once()
    process.wait.assert_awaited()
    assert process.returncode == 0
    reap.assert_called_once_with(88)


@pytest.mark.asyncio
async def test_execute_reaps_after_normal_completion():
    process = _MockProcess(pid=1001, returncode=0, stdout=b"ok\n")
    manager = ExecSessionManager()
    with (
        patch.object(ExecTool, "_spawn", return_value=process),
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
    ):
        try:
            result = await ExecTool(session_manager=manager).execute(command="echo ok")
        finally:
            await manager.close_all()

    assert not is_tool_error_result(result)
    assert "ok" in result
    assert "Exit code: 0" in result
    process.wait.assert_awaited()
    process.kill.assert_not_called()
    reap.assert_called_with(1001)


@pytest.mark.asyncio
async def test_execute_timeout_kills_and_reaps():
    process = _MockProcess(pid=1002, returncode=None)
    manager = ExecSessionManager()
    with (
        patch.object(ExecTool, "_spawn", return_value=process) as spawn,
        patch.object(ExecTool, "_kill_process_tree", side_effect=ExecTool._kill_process) as kill_tree,
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
    ):
        try:
            result = await asyncio.wait_for(
                ExecTool(timeout=1, session_manager=manager).execute(command="sleep 99", timeout=1),
                timeout=5,
            )
        finally:
            await manager.close_all()

    assert is_tool_error_result(result)
    assert "timed out" in result.lower()
    assert "Reason: max_runtime" in result
    kill_tree.assert_awaited_once_with(process)
    process.kill.assert_called_once()
    process.wait.assert_awaited()
    assert process.returncode == -9
    reap.assert_any_call(1002)
    assert spawn.await_args.kwargs["process_tree"] is True


@pytest.mark.asyncio
async def test_execute_cancellation_kills_process_tree():
    process = _MockProcess(pid=1005, returncode=None)
    manager = ExecSessionManager()
    waiting = asyncio.Event()
    wait_exit = _ExecSession.wait_exit

    async def inline_wait(session: _ExecSession) -> None:
        waiting.set()
        await wait_exit(session)

    with (
        patch.object(ExecTool, "_spawn", return_value=process) as spawn,
        patch.object(ExecTool, "_kill_process_tree", side_effect=ExecTool._kill_process) as kill_tree,
        patch.object(_ExecSession, "wait_exit", new=inline_wait),
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
    ):
        execution = asyncio.create_task(
            ExecTool(session_manager=manager).execute(command="sleep 99"),
        )
        try:
            await asyncio.wait_for(waiting.wait(), timeout=5)
            assert process.returncode is None
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(execution, timeout=5)
            assert await manager.list() == []
        finally:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            await manager.close_all()

    kill_tree.assert_awaited_once_with(process)
    process.kill.assert_called_once()
    process.wait.assert_awaited()
    assert process.returncode == -9
    reap.assert_any_call(1005)
    assert spawn.await_args.kwargs["process_tree"] is True


@pytest.mark.asyncio
async def test_exec_session_wait_cancellation_does_not_kill_process_tree():
    process = _MockProcess(pid=1007, returncode=None)
    manager = ExecSessionManager()
    session_tool = ExecSessionTool(manager=manager)
    with (
        patch.object(ExecTool, "_spawn", return_value=process),
        patch.object(ExecTool, "_kill_process_tree", side_effect=ExecTool._kill_process) as kill_tree,
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
    ):
        observer = None
        try:
            initial = await ExecTool(session_manager=manager).execute(
                command="sleep 99", yield_time_ms=0,
            )
            session_id, session = next(iter(manager._sessions.items()))
            assert session_id in initial
            observer = asyncio.create_task(session_tool.execute(
                session_id=session_id, until_exit=True, timeout_ms=30_000,
            ))
            await asyncio.sleep(0)
            assert not observer.done()
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer

            assert process.returncode is None
            assert not session._completion_task.done()
            process.kill.assert_not_called()
            kill_tree.assert_not_awaited()
            assert [info.session_id for info in await manager.list()] == [session_id]

            result = await session_tool.execute(session_id=session_id, terminate=True)
            assert "Reason: cancelled" in result
            assert "Exit code: -9" in result
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
            await manager.close_all()

    kill_tree.assert_awaited_once_with(process)
    process.kill.assert_called_once()
    reap.assert_any_call(1007)


@pytest.mark.asyncio
async def test_execute_exception_after_success_does_not_raise_on_dead_process():
    """Formatting a completed result must not attempt to kill the dead process."""
    process = _MockProcess(pid=1003, returncode=0, stdout=b"out\n")
    process.kill.side_effect = ProcessLookupError("already dead")
    manager = ExecSessionManager()
    with (
        patch.object(ExecTool, "_spawn", return_value=process),
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
        patch(
            "nanobot.agent.tools.shell.format_session_poll",
            side_effect=RuntimeError("boom after exit"),
        ) as formatter,
    ):
        try:
            result = await ExecTool(session_manager=manager).execute(command="echo out")
        finally:
            await manager.close_all()

    assert is_tool_error_result(result)
    assert "Error executing command" in result
    assert "boom after exit" in result
    poll = formatter.call_args.args[1]
    assert poll.done is True
    assert poll.exit_code == 0
    assert poll.output == "out\n"
    process.wait.assert_awaited()
    process.kill.assert_not_called()
    reap.assert_called_with(1003)


@pytest.mark.asyncio
async def test_execute_stream_read_error_kills_live_process(tmp_path):
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    spawn_process = ExecTool._spawn
    kill_process_tree = ExecTool._kill_process_tree
    process = None

    async def spawn_with_broken_stdout(*args, **kwargs):
        nonlocal process
        process = await spawn_process(*args, **kwargs)
        assert process.returncode is None
        assert process.stdout is not None
        process.stdout.set_exception(OSError("pipe broken"))
        return process

    with (
        patch.object(ExecTool, "_spawn", side_effect=spawn_with_broken_stdout),
        patch.object(ExecTool, "_kill_process_tree", wraps=kill_process_tree) as kill_tree,
        patch("nanobot.agent.tools.shell._reap_pid", wraps=_reap_pid) as reap,
    ):
        try:
            result = await asyncio.wait_for(tool.execute(
                command=[sys.executable, "-u", "-c", "import time; time.sleep(30)"],
            ), timeout=10)
        finally:
            try:
                await manager.close_all()
            finally:
                if process is not None and process.returncode is None:
                    await kill_process_tree(process)

    assert is_tool_error_result(result)
    assert "pipe broken" in result
    assert "Reason: execution_error" in result
    assert "output may be incomplete" in result
    assert "Process running" not in result
    assert process is not None
    assert process.returncode is not None and process.returncode != 0
    kill_tree.assert_awaited_once_with(process)
    reap.assert_any_call(process.pid)


@pytest.mark.asyncio
async def test_kill_process_tree_targets_group_after_root_exits():
    process = _MockProcess(pid=1006, returncode=0)

    with (
        patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
        patch("nanobot.agent.tools.shell.os.killpg", create=True) as kill_group,
        patch("nanobot.agent.tools.shell.signal.SIGKILL", 9, create=True),
        patch("nanobot.agent.tools.shell._reap_pid") as reap,
    ):
        await ExecTool._kill_process_tree(process)

    kill_group.assert_called_once_with(1006, 9)
    process.kill.assert_not_called()
    reap.assert_called_once_with(1006)


@pytest.mark.skipif(sys.platform == "win32", reason="requires Unix process groups")
@pytest.mark.asyncio
async def test_execute_timeout_kills_background_process_tree(tmp_path):
    """A one-shot timeout must stop background descendants before they write."""
    marker = tmp_path / "child-survived"
    command = f"(sleep 2; touch {shlex.quote(str(marker))}) >/dev/null 2>&1 & sleep 30"

    result = await ExecTool(working_dir=str(tmp_path), timeout=1).execute(
        command=command,
        timeout=1,
    )

    assert "timed out" in result.lower()
    await asyncio.sleep(2.5)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_kill_process_tree_kills_descendant_after_root_exits(tmp_path):
    """Tree ownership must outlive a root shell that has demonstrably exited."""
    marker = tmp_path / "child-survived-root"
    started = tmp_path / "child-started"
    release = tmp_path / "release-child"
    child_code = (
        "import pathlib,time\n"
        f"started=pathlib.Path({str(started)!r})\n"
        f"release=pathlib.Path({str(release)!r})\n"
        f"marker=pathlib.Path({str(marker)!r})\n"
        "started.write_text('ready')\n"
        "while not release.exists():\n"
        "    time.sleep(0.01)\n"
        "marker.write_text('alive')\n"
    )
    child_payload = base64.b64encode(child_code.encode()).decode()
    # Do not let the descendant keep the root's captured pipes open; the test
    # must observe root exit independently from descendant lifetime.
    parent_code = (
        "import base64,subprocess,sys; "
        f"child=base64.b64decode('{child_payload}').decode(); "
        "subprocess.Popen([sys.executable, '-c', child], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    tool = ExecTool(working_dir=str(tmp_path), timeout=10)
    process = await tool._spawn(
        _python_command(parent_code),
        str(tmp_path),
        tool._build_env(),
        process_tree=True,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
        assert process.returncode == 0
        async with asyncio.timeout(10):
            while not started.exists():
                await asyncio.sleep(0.01)

        await ExecTool._kill_process_tree(process)
        await asyncio.wait_for(process.communicate(), timeout=5)
        release.write_text("go")
        await asyncio.sleep(1)
        assert not marker.exists()
    finally:
        await ExecTool._kill_process_tree(process)


@pytest.mark.asyncio
async def test_exec_session_kill_reaps():
    process = _MockProcess(pid=2001, returncode=None)
    session = _ExecSession(
        session_id="abc",
        process=process,
        command="sleep 1",
        cwd="/tmp",
        timeout=30,
        owner_session_key=None,
    )
    try:
        with patch("nanobot.agent.tools.shell._reap_pid") as reap:
            await session.kill()
        process.kill.assert_called_once()
        process.wait.assert_awaited()
        assert process.returncode == -9
        assert session.finish_reason == "cancelled"
        assert session.finished_at is not None
        reap.assert_any_call(2001)
    finally:
        await _cleanup_session(session)


@pytest.mark.asyncio
async def test_exec_session_kill_reaps_if_process_exits_before_kill():
    process = _MockProcess(pid=2002, returncode=None)

    def raced_exit() -> None:
        process.exit(0)
        raise ProcessLookupError("raced exit")

    process.kill.side_effect = raced_exit
    session = _ExecSession(
        session_id="raced",
        process=process,
        command="sleep 1",
        cwd="/tmp",
        timeout=30,
        owner_session_key=None,
    )
    try:
        with patch("nanobot.agent.tools.shell._reap_pid") as reap:
            await session.kill()
        process.kill.assert_called_once()
        process.wait.assert_awaited()
        assert process.returncode == 0
        assert session.finished_at is not None
        reap.assert_any_call(2002)
    finally:
        await _cleanup_session(session)


@pytest.mark.asyncio
async def test_exec_session_kill_waits_for_reader_tasks():
    process = _MockProcess(pid=2003, returncode=None, stdout=b"head\n")
    # OS exit can be observed before the readers have consumed the final pipe bytes.
    process.kill.side_effect = lambda: process.exit(-9, close_streams=False)
    session = _ExecSession(
        session_id="readers",
        process=process,
        command="sleep 1",
        cwd="/tmp",
        timeout=30,
        owner_session_key=None,
    )
    stopping = asyncio.create_task(session.kill())
    try:
        await asyncio.wait_for(process.exited.wait(), timeout=5)
        await process.wait()
        done, _ = await asyncio.wait({stopping}, timeout=0.05)
        assert not done, "kill returned before stdout/stderr reached EOF"
        assert session.finished_at is None

        process.stdout.feed_data(b"tail\n")
        process.stderr.feed_data(b"error tail\n")
        process.stdout.feed_eof()
        process.stderr.feed_eof()
        await asyncio.wait_for(stopping, timeout=5)

        assert session._stdout_task.done()
        assert session._stderr_task.done()
        poll = await session.poll(yield_time_ms=0, max_output_chars=1000)
        assert poll.done is True
        assert poll.output == "head\ntail\n\nSTDERR:\nerror tail\n"
        assert not poll.output_incomplete
    finally:
        process.stdout.feed_eof()
        process.stderr.feed_eof()
        await asyncio.gather(stopping, return_exceptions=True)
        await _cleanup_session(session)


@pytest.mark.asyncio
async def test_exec_session_poll_reaps_after_exit():
    process = _MockProcess(pid=2004, returncode=0, stdout=b"hi\n")
    session = _ExecSession(
        session_id="def",
        process=process,
        command="echo hi",
        cwd="/tmp",
        timeout=30,
        owner_session_key=None,
    )
    try:
        with patch("nanobot.agent.tools.shell._reap_pid") as reap:
            await asyncio.wait_for(session.wait_exit(), timeout=5)
            poll = await session.poll(yield_time_ms=0, max_output_chars=1000)
        assert poll.done is True
        assert poll.exit_code == 0
        assert poll.output == "hi\n"
        assert poll.finish_reason == "exit"
        process.kill.assert_not_called()
        reap.assert_called_with(2004)
    finally:
        await _cleanup_session(session)


@pytest.mark.skipif(sys.platform == "win32", reason="zombie reaping is a Unix waitpid concern")
@pytest.mark.asyncio
async def test_real_timeout_leaves_no_zombie(tmp_path):
    """Integration: timed-out sleep should not leave a defunct child of this process."""
    import os

    tool = ExecTool(working_dir=str(tmp_path), timeout=1)
    result = await tool.execute(command="sleep 30", timeout=1)
    assert "timed out" in result.lower()

    await asyncio.sleep(0.05)
    reaped = []
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            break
        reaped.append((pid, status))
    assert reaped == [], f"unreaped children left as zombies: {reaped}"
