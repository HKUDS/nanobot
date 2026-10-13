from __future__ import annotations

import asyncio
import re
import sys

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.shell import ExecTool


def _session_id(result: str) -> str:
    match = re.search(r"session_id:\s*([0-9a-f]+)", result)
    assert match, result
    return match.group(1)


async def test_exec_session_hard_timeout_kills_process_tree_without_polling(tmp_path):
    ready = tmp_path / "child-started.txt"
    late_write = tmp_path / "child-survived-timeout.txt"
    child_code = (
        "import pathlib,time; "
        f"pathlib.Path({str(ready)!r}).write_text('started'); "
        "time.sleep(3); "
        f"pathlib.Path({str(late_write)!r}).write_text('survived timeout')"
    )
    parent_code = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable, '-u', '-c', {child_code!r}]); "
        "print('parent started', flush=True); child.wait()"
    )
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), timeout=1, session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)

    try:
        initial = await tool.execute(
            command=[sys.executable, "-u", "-c", parent_code], yield_time_ms=0,
        )
        sid = _session_id(initial)
        session = manager._sessions[sid]

        # Waiting on the OS process must not need another nanobot tool call to enforce
        # the deadline. The child inherits the pipes, so an orphan would also delay EOF.
        await asyncio.wait_for(session.process.wait(), timeout=6)
        await asyncio.wait_for(
            asyncio.gather(session._stdout_task, session._stderr_task), timeout=2,
        )

        assert ready.exists(), "the descendant must have started before the timeout"
        assert not late_write.exists(), "the descendant wrote after the hard timeout"
        assert session.process.returncode != 0

        final = await session_tool.execute(session_id=sid, timeout_ms=0)
        assert is_tool_error_result(final)
        assert "Command timed out; session was terminated." in final
        assert "parent started" in initial + final
        assert "Process running" not in final
        assert sid not in manager._sessions
    finally:
        await manager.close_all()


async def test_exec_session_completed_before_deadline_keeps_output_for_late_poll(tmp_path):
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), timeout=1, session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)

    try:
        initial = await tool.execute(
            command=[
                sys.executable, "-u", "-c",
                "import time; time.sleep(0.1); print('completed normally')",
            ],
            yield_time_ms=0,
        )
        sid = _session_id(initial)
        await asyncio.wait_for(manager._sessions[sid].process.wait(), timeout=3)
        # Read only after the original deadline: completion must not turn into a timeout.
        await asyncio.sleep(1.1)

        final = await session_tool.execute(session_id=sid, timeout_ms=0)
        assert not is_tool_error_result(final)
        assert "completed normally" in initial + final
        assert "Exit code: 0" in final
        assert "timed out" not in final
        assert sid not in manager._sessions
    finally:
        await manager.close_all()


async def test_exec_session_zero_config_timeout_allows_unpolled_longer_process(tmp_path):
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), timeout=0, session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)

    try:
        initial = await tool.execute(
            command=[
                sys.executable, "-u", "-c",
                "import time; time.sleep(1.2); print('completed without deadline')",
            ],
            yield_time_ms=0,
        )
        sid = _session_id(initial)
        await asyncio.wait_for(manager._sessions[sid].process.wait(), timeout=5)

        final = await session_tool.execute(session_id=sid, timeout_ms=0)
        assert not is_tool_error_result(final)
        assert "completed without deadline" in initial + final
        assert "Exit code: 0" in final
        assert "timed out" not in final
        assert sid not in manager._sessions
    finally:
        await manager.close_all()
