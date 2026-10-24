"""filter_stderr_noise drops the xcrun cache-denial noise the seatbelt profile cannot allow.

On stock macOS the ``/usr/bin`` toolchain shims (``git`` via the xcrun shim)
must open/replace their shared ``xcrun_db`` cache under the host DARWIN_USER
temp dir, which the seatbelt profile intentionally keeps private. The denial
does not affect the command's outcome but injects two
``couldn't <verb> cache file ... (errno=Operation not permitted)`` lines into
every invocation's stderr, which otherwise surfaces to the agent as a
spurious STDERR section that reads like a failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanobot.agent.tools.shell_output import filter_stderr_noise

NOISE_LINES = [
    "git: error: couldn't create cache file '/var/folders/xx/T/xcrun_db-ABC' (errno=Operation not permitted)",
    "git: error: couldn't open cache file '/var/folders/xx/T/xcrun_db-ABC' (errno=Operation not permitted)",
    "swift: error: couldn't replace cache file '/var/folders/xx/T/xcrun_db-ABC' (errno=Operation not permitted)",
]


def test_noise_lines_are_dropped():
    stderr = "\n".join(NOISE_LINES) + "\n"
    assert filter_stderr_noise(stderr) == ""


def test_real_errors_are_preserved():
    stderr = (
        "git: error: couldn't create cache file '/var/folders/xx/T/xcrun_db-ABC' (errno=Operation not permitted)\n"
        "fatal: not a git repository\n"
    )
    assert filter_stderr_noise(stderr) == "fatal: not a git repository\n"


def test_non_xcrun_stderr_untouched():
    stderr = "warning: something minor\nerror: real failure\n"
    assert filter_stderr_noise(stderr) == stderr


def test_similar_but_different_errors_kept():
    # A cache-file error about a different file, or a different errno, is a
    # real error and must survive.
    stderr = (
        "git: error: couldn't create cache file '/tmp/other_db' (errno=Operation not permitted)\n"
        "git: error: couldn't create cache file '/var/folders/xx/T/xcrun_db-ABC' (errno=No space left on device)\n"
    )
    assert filter_stderr_noise(stderr) == stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS xcrun shim")
async def test_git_stderr_is_clean_under_seatbelt(tmp_path: Path):
    """Every git call inside the seatbelt sandbox stays free of xcrun noise."""
    from nanobot.agent.tools.shell import ExecTool

    ws = tmp_path / "ws"
    ws.mkdir()
    tool = ExecTool(working_dir=str(ws), sandbox="seatbelt")
    result = str(await tool.execute(command="git --version", timeout=10))
    assert "git version " in result
    assert "Exit code: 0" in result
    assert "couldn't create cache file" not in result
    assert "couldn't open cache file" not in result
    assert "couldn't replace cache file" not in result
    assert "STDERR" not in result
