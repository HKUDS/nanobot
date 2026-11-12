"""Plain-text output through shell tools and streaming filters."""

from __future__ import annotations

import re
import sys

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.shell_output import ShellOutputFilter


@pytest.mark.parametrize("chunk_size", [1, 4096])
def test_filter_preserves_text_and_layout_across_terminal_sequences(chunk_size):
    source = (
        "\x1b]0;Weather report\x07"
        "北京\t\x1b[1;38;5;190m+21\x1b[0m °C\r\n"
        "│  Morning  │  Noon  │\n"
        "\x1b[?25l\x1b[2K"
        "\x1b]8;;https://example.com\x1b\\forecast\x1b]8;;\x1b\\\n"
        "\x1b(B\x1b_Gimage payload\x1b\\"
        "  🙂\n\n"
        r"literal \x1b[31m and \u001b[0m"
    )
    expected = (
        "北京\t+21 °C\r\n"
        "│  Morning  │  Noon  │\n"
        "forecast\n"
        "  🙂\n\n"
        r"literal \x1b[31m and \u001b[0m"
    )
    output_filter = ShellOutputFilter()

    result = "".join(
        output_filter.feed(source[start:start + chunk_size])
        for start in range(0, len(source), chunk_size)
    )

    assert result == expected


@pytest.mark.parametrize("yield_time_ms", [None, 1000])
async def test_exec_filters_before_output_limits_and_preserves_status(tmp_path, yield_time_ms):
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), timeout=10, session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)
    visible = "北京\t+21 °C\n│  Morning  │  Noon  │\n"
    stderr = "\x1b[31mwarning: haze\x1b[0m\n"
    command = [
        sys.executable, "-X", "utf8", "-c",
        "import sys; "
        f"sys.stdout.write('\\x1b[38;5;190m' * 5000 + {visible!r} + '\\x1b[0m'); "
        f"sys.stderr.write({stderr!r}); sys.exit(7)",
    ]
    try:
        result = await tool.execute(
            command=command, yield_time_ms=yield_time_ms, max_output_chars=1000,
        )
        session = re.search(r"session_id: ([0-9a-f]+)", result)
        if session:
            result += await session_tool.execute(session_id=session.group(1), until_exit=True)

        assert visible in result.replace("\r\n", "\n")
        assert "STDERR:\nwarning: haze" in result
        assert "Exit code: 7" in result
        assert "\x1b" not in result
        assert "truncated" not in result
    finally:
        await manager.close_all()


async def test_exec_session_filters_split_sequences_and_waits_for_visible_text(tmp_path):
    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), timeout=10, session_manager=manager)
    session_tool = ExecSessionTool(manager=manager)
    command = [
        sys.executable, "-u", "-c",
        "import sys; "
        "sys.stdout.write('before\\x1b[38;5;'); sys.stdout.flush(); "
        "sys.stderr.write('\\x1b[31mwarning\\x1b[0m\\n'); sys.stderr.flush(); "
        "sys.stdin.readline(); "
        "sys.stdout.write('190mr\\x1b[1meady\\x1b[0m\\n'); sys.stdout.flush(); "
        "sys.stdin.readline()",
    ]
    try:
        initial = await tool.execute(command=command, yield_time_ms=1000)
        session = re.search(r"session_id: ([0-9a-f]+)", initial)
        assert session, initial
        session_id = session.group(1)
        ready = await session_tool.execute(session_id=session_id, input="\n", wait_for="ready")
        final = await session_tool.execute(session_id=session_id, input="\n", until_exit=True)

        assert "ready" in ready
        assert "Wait target not observed" not in ready
        assert "Process running." in ready
        assert "Exit code: 0" in final
        combined = initial + ready + final
        assert "before" in combined
        assert "STDERR:\nwarning" in combined
        assert "\x1b" not in combined
        assert "38;5;" not in combined
        assert "190m" not in combined
    finally:
        await manager.close_all()
