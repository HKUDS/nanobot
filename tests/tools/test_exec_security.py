"""Tests for exec tool internal URL blocking."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.agent.tools.shell import ExecTool


def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_localhost(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.asyncio
async def test_exec_blocks_curl_metadata():
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(
            command='curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/'
        )
    assert "Error" in result
    assert "internal" in result.lower() or "private" in result.lower()


@pytest.mark.asyncio
async def test_exec_blocks_wget_localhost():
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_localhost):
        result = await tool.execute(command="wget http://localhost:8080/secret -O /tmp/out")
    assert "Error" in result


@pytest.mark.asyncio
async def test_exec_allows_normal_commands():
    tool = ExecTool(timeout=5)
    result = await tool.execute(command="echo hello")
    assert "hello" in result
    assert "Error" not in result.split("\n")[0]


@pytest.mark.asyncio
async def test_exec_allows_curl_to_public_url():
    """Commands with public URLs should not be blocked by the internal URL check."""
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        guard_result = tool._guard_command("curl https://example.com/api", "/tmp")
    assert guard_result is None


@pytest.mark.asyncio
async def test_exec_blocks_chained_internal_url():
    """Internal URLs buried in chained commands should still be caught."""
    tool = ExecTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(
            command="echo start && curl http://169.254.169.254/latest/meta-data/ && echo done"
        )
    assert "Error" in result


# --- allow_patterns whitelist tests ---

HOMER_ALLOW = [r"^/opt/homer/\.venv/bin/python /opt/homer/tools/\w+\.py(\s|$)"]


@pytest.mark.asyncio
async def test_allowlist_permits_approved_script():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/gmail_fetch.py --hours 24", "/tmp"
    )
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_permits_script_no_args():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py", "/tmp"
    )
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_blocks_cat_config():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("cat ~/.nanobot/config.json", "/tmp")
    assert guard is not None
    assert "allowlist" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_cat_secrets():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("cat /opt/homer/secrets/.env", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_arbitrary_python():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("python3 -c 'import os; print(os.environ)'", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_ls():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("ls /opt/homer/secrets/", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_grep():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("grep -r API_KEY /opt/homer/", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_sed_production_patch():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "sed -i 's/old/new/' /opt/homer/tools/context_updater.py", "/tmp"
    )
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_curl():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("curl https://example.com", "/tmp")
    assert guard is not None


@pytest.mark.asyncio
async def test_allowlist_blocks_pipe_after_approved_script():
    """Chaining a pipe after an approved script should still be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py | cat ~/.nanobot/config.json", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_ampersand_chain():
    """Chaining && after an approved script should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py && cat /etc/passwd", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_semicolon_chain():
    """Chaining ; after an approved script should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py ; cat secrets", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_backtick_injection():
    """Backtick command substitution should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py `cat secrets`", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_dollar_paren_injection():
    """$() command substitution should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py $(cat secrets)", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_no_allowlist_permits_everything():
    """Without allow_patterns, all non-dangerous commands pass."""
    tool = ExecTool(allow_patterns=None)
    guard = tool._guard_command("cat /etc/passwd", "/tmp")
    assert guard is None


@pytest.mark.asyncio
async def test_allowlist_blocks_newline_injection():
    """Newline injection to run a second command should be blocked."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/version.py\ncat ~/.nanobot/config.json", "/tmp"
    )
    assert guard is not None
    assert "metacharacter" in guard.lower()


@pytest.mark.asyncio
async def test_allowlist_blocks_echo():
    tool = ExecTool(allow_patterns=HOMER_ALLOW)
    guard = tool._guard_command("echo hello", "/tmp")
    assert guard is not None


# --- allowlist + restrictToWorkspace interaction tests ---

GUEST_WORKSPACE = "/opt/homer/context/.guest_workspace"


@pytest.mark.asyncio
async def test_allowlisted_command_bypasses_workspace_restriction():
    """An allowlisted exec command should not be blocked by restrictToWorkspace,
    even though the command contains paths outside the workspace."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/deliver_escalation.py --list-pending",
        GUEST_WORKSPACE,
    )
    assert guard is None


@pytest.mark.asyncio
async def test_allowlisted_command_with_args_bypasses_workspace_restriction():
    """Allowlisted commands with arguments should also bypass workspace restriction."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/escalate.py --trigger-type question --message \"test\"",
        GUEST_WORKSPACE,
    )
    assert guard is None


@pytest.mark.asyncio
async def test_non_allowlisted_command_still_blocked_by_workspace():
    """Commands not matching allowPatterns should still be blocked by restrictToWorkspace."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command("cat /etc/passwd", GUEST_WORKSPACE)
    assert guard is not None
    assert "allowlist" in guard.lower()


@pytest.mark.asyncio
async def test_workspace_restriction_blocks_outside_paths_without_allowlist():
    """Without allowPatterns, restrictToWorkspace should block paths outside the workspace."""
    tool = ExecTool(restrict_to_workspace=True)
    guard = tool._guard_command(
        "cat /opt/homer/secrets/.env", GUEST_WORKSPACE
    )
    assert guard is not None
    assert "outside" in guard.lower()


@pytest.mark.asyncio
async def test_workspace_restriction_allows_inside_paths_without_allowlist():
    """Without allowPatterns, restrictToWorkspace should allow paths inside the workspace."""
    tool = ExecTool(restrict_to_workspace=True)
    guard = tool._guard_command(
        "cat /opt/homer/context/.guest_workspace/USER.md", GUEST_WORKSPACE
    )
    assert guard is None


@pytest.mark.asyncio
async def test_workspace_restriction_blocks_traversal_without_allowlist():
    """Path traversal should still be blocked even without allowPatterns."""
    tool = ExecTool(restrict_to_workspace=True)
    guard = tool._guard_command("cat ../../secrets/.env", GUEST_WORKSPACE)
    assert guard is not None
    assert "traversal" in guard.lower()


@pytest.mark.asyncio
async def test_allowlisted_command_blocks_traversal_in_args():
    """Path traversal in arguments should be blocked even for allowlisted commands."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/escalate.py --file ../../secrets/.env",
        GUEST_WORKSPACE,
    )
    assert guard is not None
    assert "traversal" in guard.lower()


@pytest.mark.asyncio
async def test_allowlisted_command_blocks_outside_path_in_args():
    """Absolute paths outside workspace in arguments should be blocked for allowlisted commands."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/escalate.py --file /etc/passwd",
        GUEST_WORKSPACE,
    )
    assert guard is not None
    assert "outside" in guard.lower()


@pytest.mark.asyncio
async def test_allowlisted_command_allows_workspace_path_in_args():
    """Absolute paths inside workspace in arguments should be allowed for allowlisted commands."""
    tool = ExecTool(allow_patterns=HOMER_ALLOW, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/escalate.py --file /opt/homer/context/.guest_workspace/data.json",
        GUEST_WORKSPACE,
    )
    assert guard is None


@pytest.mark.asyncio
async def test_multiple_allow_patterns_all_paths_exempted():
    """When multiple patterns match, paths from all matches should be exempted."""
    patterns = [
        r"^/opt/homer/\.venv/bin/python",
        r"/opt/homer/tools/\w+\.py",
    ]
    tool = ExecTool(allow_patterns=patterns, restrict_to_workspace=True)
    guard = tool._guard_command(
        "/opt/homer/.venv/bin/python /opt/homer/tools/escalate.py --list-pending",
        GUEST_WORKSPACE,
    )
    assert guard is None


# --- #2989: block writes to nanobot internal state files -----------------


@pytest.mark.parametrize(
    "command",
    [
        "cat foo >> history.jsonl",
        "echo '{}' > history.jsonl",
        "echo '{}' > memory/history.jsonl",
        "echo '{}' > ./workspace/memory/history.jsonl",
        "tee -a history.jsonl < foo",
        "tee history.jsonl",
        "cp /tmp/fake.jsonl history.jsonl",
        "mv backup.jsonl memory/history.jsonl",
        "dd if=/dev/zero of=memory/history.jsonl",
        "sed -i 's/old/new/' history.jsonl",
        "echo x > .dream_cursor",
        "cp /tmp/x memory/.dream_cursor",
    ],
)
def test_exec_blocks_writes_to_history_jsonl(command):
    """Direct writes to history.jsonl / .dream_cursor must be blocked (#2989)."""
    tool = ExecTool()
    result = tool._guard_command(command, "/tmp")
    assert result is not None
    assert "dangerous pattern" in result.lower()


@pytest.mark.parametrize(
    "command",
    [
        "cat history.jsonl",
        "wc -l history.jsonl",
        "tail -n 5 history.jsonl",
        "grep foo history.jsonl",
        "cp history.jsonl /tmp/history.backup",
        "ls memory/",
        "echo history.jsonl",
    ],
)
def test_exec_allows_reads_of_history_jsonl(command):
    """Read-only access to history.jsonl must still be allowed."""
    tool = ExecTool()
    result = tool._guard_command(command, "/tmp")
    assert result is None


# --- #2826: working_dir must not escape the configured workspace ---------


@pytest.mark.asyncio
async def test_exec_blocks_working_dir_outside_workspace(tmp_path):
    """An LLM-supplied working_dir outside the workspace must be rejected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = ExecTool(working_dir=str(workspace), restrict_to_workspace=True)
    result = await tool.execute(command="rm calendar.ics", working_dir="/etc")
    assert "outside the configured workspace" in result


@pytest.mark.asyncio
async def test_exec_blocks_absolute_rm_via_hijacked_working_dir(tmp_path):
    """Regression for #2826: `rm /abs/path` via working_dir hijack."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    victim_dir = tmp_path / "outside"
    victim_dir.mkdir()
    victim = victim_dir / "file.ics"
    victim.write_text("data")

    tool = ExecTool(working_dir=str(workspace), restrict_to_workspace=True)
    result = await tool.execute(
        command=f"rm {victim}",
        working_dir=str(victim_dir),
    )
    assert "outside the configured workspace" in result
    assert victim.exists(), "victim file must not have been deleted"


@pytest.mark.asyncio
async def test_exec_allows_working_dir_within_workspace(tmp_path):
    """A working_dir that is a subdirectory of the workspace is fine."""
    workspace = tmp_path / "workspace"
    subdir = workspace / "project"
    subdir.mkdir(parents=True)
    tool = ExecTool(working_dir=str(workspace), restrict_to_workspace=True, timeout=5)
    result = await tool.execute(command="echo ok", working_dir=str(subdir))
    assert "ok" in result
    assert "outside the configured workspace" not in result


@pytest.mark.asyncio
async def test_exec_allows_working_dir_equal_to_workspace(tmp_path):
    """Passing working_dir equal to the workspace root must be allowed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = ExecTool(working_dir=str(workspace), restrict_to_workspace=True, timeout=5)
    result = await tool.execute(command="echo ok", working_dir=str(workspace))
    assert "ok" in result
    assert "outside the configured workspace" not in result


@pytest.mark.asyncio
async def test_exec_ignores_workspace_check_when_not_restricted(tmp_path):
    """Without restrict_to_workspace, the LLM may still choose any working_dir."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    tool = ExecTool(working_dir=str(workspace), restrict_to_workspace=False, timeout=5)
    result = await tool.execute(command="echo ok", working_dir=str(other))
    assert "ok" in result
    assert "outside the configured workspace" not in result
