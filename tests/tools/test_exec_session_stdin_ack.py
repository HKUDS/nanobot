"""Regression test: exec_session must not lose the ``Stdin closed.`` report.

``ExecSessionTool._wait`` sends ``input`` and ``close_stdin`` on the first
poll iteration only.  ``manager.write`` derives ``stdin_closed`` from that
call's ``close_stdin`` argument, so the flag lives on the *first* poll object.
When the wait loop iterates again (``wait_for`` matched later, or the deadline
expired), the tool formats the *last* poll — and the confirmation that stdin
was closed is silently dropped, leaving the model unable to tell whether
``close_stdin`` took effect.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell pipeline under test")


async def test_wait_for_reports_stdin_closed_across_poll_iterations() -> None:
    manager = ExecSessionManager()
    tool = ExecSessionTool(manager=manager)

    # Prints "start"; after receiving one stdin line, sleeps past one poll
    # step (500 ms) and only then prints the wait_for target, then exits on
    # the EOF caused by close_stdin.  This forces _wait through at least two
    # poll iterations while stdin was closed during the first one.
    command = "printf '%s\\n' start; IFS= read -r _; sleep 1.2; printf '%s\\n' done-marker"
    session_id, first = await manager.start(
        command=command,
        cwd=os.getcwd(),
        env={"HOME": os.environ.get("HOME", "/tmp"), "PATH": os.environ.get("PATH", "")},
        timeout=None,
        shell_program=None,
        login=False,
        yield_time_ms=0,
        max_output_chars=10_000,
    )
    try:
        assert not first.done

        result = await asyncio.wait_for(
            tool.execute(
                session_id=session_id,
                input="go\n",
                close_stdin=True,
                wait_for="done-marker",
                timeout_ms=10_000,
            ),
            timeout=30,
        )

        # The wait must have observed its target…
        assert "Wait target not observed" not in result
        # …and the first iteration accepted the stdin close, so the final
        # report must still confirm it instead of silently dropping the flag.
        assert "Stdin closed." in result
    finally:
        await manager.close_all()
