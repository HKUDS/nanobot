"""Tests for allow_patterns priority over deny_patterns."""

from __future__ import annotations

import shlex
import sys
import tempfile
from pathlib import Path

import pytest

from nanobot.agent.tools.shell import ExecTool


def test_deny_patterns_block_rm_rf():
    """Baseline: rm -rf is blocked by default deny list."""
    tool = ExecTool()
    result = tool._guard_command("rm -rf /", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp/nanobot-test",
        "rm -fr /tmp/nanobot-test-*",
        "rm --recursive --force /tmp/nanobot-test-cache",
        "echo setup && rm -rf /tmp/nanobot-test; echo done",
        "bash -lc 'pytest tests; rm -rf /tmp/nanobot-test'",
        "rm -rf '/tmp/nanobot test' 2>/dev/null",
    ],
)
def test_deny_patterns_allow_scoped_tmp_cleanup(command):
    """Named, static /tmp descendants are safe enough for test cleanup."""
    tool = ExecTool()
    assert tool._guard_command(command, "/tmp") is None


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp",
        "rm -rf /tmp/*",
        "rm -rf /tmp/nanobot-test/../../etc",
        "rm -rf /tmp/nanobot-test/cache",
        "rm -rf /tmp/$TARGET",
        "rm -rf /tmp/nanobot-test /etc",
        "rm -rf /tmp/nanobot-test >/etc/passwd",
        "echo setup && rm -rf /etc",
    ],
)
def test_deny_patterns_block_unscoped_recursive_rm(command):
    """Broad, dynamic, traversing, or mixed recursive deletions remain blocked."""
    tool = ExecTool()
    result = tool._guard_command(command, "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_deny_patterns_allow_non_recursive_rm_f():
    """The recursive-delete guard must not mistake rm -f for rm -rf."""
    tool = ExecTool()
    assert tool._guard_command("rm -f /tmp/nanobot-test.log", "/tmp") is None


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX rm and /tmp syntax")
async def test_exec_runs_scoped_tmp_cleanup():
    """A real exec call can remove its own directly named temporary directory."""
    with tempfile.TemporaryDirectory(prefix="nanobot-exec-cleanup-", dir="/tmp") as temp_dir:
        target = Path(temp_dir)
        (target / "scratch.txt").write_text("scratch")
        tool = ExecTool(timeout=5)

        result = await tool.execute(command=f"rm -rf {shlex.quote(temp_dir)}")

        assert "deny pattern filter" not in result.lower()
        assert not target.exists()


def test_allow_patterns_bypass_deny():
    """allow_patterns take priority: matching command skips deny check."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/opt/build"])
    result = tool._guard_command("rm -rf /opt/build", "/tmp")
    assert result is None


def test_allow_patterns_must_match_to_bypass():
    """Non-matching allow_patterns do NOT bypass deny."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/tmp/build"])
    result = tool._guard_command("rm -rf /opt/build", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_extra_deny_patterns_from_config():
    """User-supplied deny patterns are appended to built-in list."""
    tool = ExecTool(deny_patterns=[r"\bping\b"])
    # ping is blocked by extra deny
    assert tool._guard_command("ping example.com", "/tmp") is not None
    # rm -rf still blocked by built-in deny
    assert tool._guard_command("rm -rf /", "/tmp") is not None


def test_extra_deny_patterns_can_block_scoped_tmp_cleanup():
    """User-configured policy still takes precedence over the built-in exception."""
    tool = ExecTool(deny_patterns=[r"\brm\b"])
    result = tool._guard_command("rm -rf /tmp/nanobot-test", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_allow_patterns_bypass_extra_deny():
    """allow_patterns also bypasses user-supplied deny patterns."""
    tool = ExecTool(
        deny_patterns=[r"\bping\b"],
        allow_patterns=[r"\bping\s+example\.com\b"],
    )
    result = tool._guard_command("ping example.com", "/tmp")
    assert result is None


def test_allow_patterns_is_whitelist_only():
    """When allow_patterns is set, non-matching non-denied commands are blocked."""
    tool = ExecTool(allow_patterns=[r"echo\s+hello"])
    # echo matches allow → ok
    assert tool._guard_command("echo hello", "/tmp") is None
    # ls does not match allow and is not in deny → blocked by allowlist
    result = tool._guard_command("ls /tmp", "/tmp")
    assert result is not None
    assert "allowlist" in result.lower()


def test_allow_patterns_do_not_allow_chained_command_bypass():
    """A partial allowlist match must not bypass deny patterns in chained commands."""
    tool = ExecTool(allow_patterns=[r"\becho\b"])
    result = tool._guard_command("echo hello; rm -rf /", "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_allow_patterns_do_not_allow_comment_tail_bypass():
    """Comment tails must not make a non-allowlisted command match."""
    tool = ExecTool(allow_patterns=[r"echo allowlisted"])
    result = tool._guard_command("touch canary # echo allowlisted", "/tmp")
    assert result is not None
    assert "allowlist" in result.lower()


def test_deny_patterns_search_original_command_with_quoted_hash():
    """Deny checks must still inspect text after a quoted hash."""
    tool = ExecTool(deny_patterns=[r"\brm\s+-rf\s+/"])
    result = tool._guard_command('echo "#"; rm -rf /', "/tmp")
    assert result is not None
    assert "deny pattern filter" in result.lower()


def test_allow_patterns_fullmatch_allows_exact_command():
    """A full-command allow pattern can still exempt an exact denied command."""
    tool = ExecTool(allow_patterns=[r"rm\s+-rf\s+/opt/build"])
    result = tool._guard_command("rm -rf /opt/build", "/tmp")
    assert result is None
