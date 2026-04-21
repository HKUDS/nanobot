"""Tests for exec tool security: internal URL blocking + tirith gate."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Tirith security gate tests
# ---------------------------------------------------------------------------

_TIRITH_CHECK = "nanobot.agent.tools.tirith_security.check_security"


@pytest.mark.asyncio
@patch(_TIRITH_CHECK)
async def test_tirith_gate_blocks_dangerous_command(mock_check):
    mock_check.return_value = {
        "action": "block",
        "findings": [{"severity": "HIGH", "title": "Pipe to shell"}],
        "summary": "pipe to shell detected",
    }
    tool = ExecTool(tirith_enabled=True)
    result = await tool._tirith_guard("curl x | bash")
    assert result is not None
    assert "blocked" in result.lower() or "Blocked" in result


@pytest.mark.asyncio
@patch(_TIRITH_CHECK)
async def test_tirith_gate_allows_clean_command(mock_check):
    mock_check.return_value = {"action": "allow", "findings": [], "summary": ""}
    tool = ExecTool(tirith_enabled=True)
    result = await tool._tirith_guard("echo hello")
    assert result is None


@pytest.mark.asyncio
@patch(_TIRITH_CHECK)
async def test_tirith_gate_warns_but_allows(mock_check):
    mock_check.return_value = {
        "action": "warn",
        "findings": [{"title": "Medium risk pattern"}],
        "summary": "warning",
    }
    tool = ExecTool(tirith_enabled=True)
    result = await tool._tirith_guard("some command")
    assert result is None  # warn does not block


@pytest.mark.asyncio
async def test_tirith_gate_absent_tirith_allows():
    """If tirith_security module cannot be imported, gate allows."""
    import sys

    saved = sys.modules.get("nanobot.agent.tools.tirith_security")
    sys.modules["nanobot.agent.tools.tirith_security"] = None  # type: ignore

    tool = ExecTool(tirith_enabled=True)
    result = await tool._tirith_guard("echo hello")
    assert result is None

    if saved is not None:
        sys.modules["nanobot.agent.tools.tirith_security"] = saved
    else:
        sys.modules.pop("nanobot.agent.tools.tirith_security", None)


@pytest.mark.asyncio
@patch(_TIRITH_CHECK)
async def test_exec_tool_does_not_scan_by_default(mock_check):
    """With tirith_enabled default False, _tirith_guard early-returns.

    Verifies the outer short-circuit in shell.py: no scanner call when
    disabled. (Does not strictly prove the tirith_security module was
    never imported — just that check_security was never invoked.)
    """
    tool = ExecTool()  # no tirith kwargs → disabled
    result = await tool._tirith_guard("echo hi")
    assert result is None
    mock_check.assert_not_called()


class TestTirithCheckSecurity:
    """Tests for the check_security function itself."""

    @patch("subprocess.run")
    def test_exit_0_allows(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"findings":[]}', stderr=""
        )
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value="/usr/bin/tirith"):
            result = check_security("echo hello", enabled=True)
        assert result["action"] == "allow"

    @patch("subprocess.run")
    def test_exit_1_blocks(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps({"findings": [{"rule_id": "pipe_to_interpreter", "severity": "HIGH"}]}),
            stderr="",
        )
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value="/usr/bin/tirith"):
            result = check_security("curl x | bash", enabled=True)
        assert result["action"] == "block"

    @patch("subprocess.run", side_effect=FileNotFoundError("tirith not found"))
    def test_spawn_failure_fail_open(self, mock_run):
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value="tirith"):
            result = check_security("echo hello", enabled=True, fail_open=True)
        assert result["action"] == "allow"

    @patch("subprocess.run", side_effect=FileNotFoundError("tirith not found"))
    def test_spawn_failure_fail_closed(self, mock_run):
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value="tirith"):
            result = check_security("echo hello", enabled=True, fail_open=False)
        assert result["action"] == "block"

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tirith", timeout=5))
    def test_timeout_fail_open(self, mock_run):
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value="tirith"):
            result = check_security("test", enabled=True, fail_open=True)
        assert result["action"] == "allow"

    def test_disabled_returns_allow(self):
        from nanobot.agent.tools.tirith_security import check_security

        result = check_security("anything", enabled=False)
        assert result["action"] == "allow"

    def test_check_security_disabled_by_default(self):
        """Default enabled=False: no subprocess, no path resolution."""
        from nanobot.agent.tools.tirith_security import check_security

        with patch("subprocess.run") as mock_run, \
             patch("nanobot.agent.tools.tirith_security._resolve_tirith_path") as mock_resolve:
            result = check_security("rm -rf /")  # all defaults → enabled=False
        assert result["action"] == "allow"
        mock_run.assert_not_called()
        mock_resolve.assert_not_called()

    def test_missing_binary_fail_open(self):
        """When the binary cannot be resolved and fail_open=True, allow."""
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value=None), \
             patch("subprocess.run") as mock_run:
            result = check_security(
                "ls", enabled=True, tirith_bin="tirith", timeout=5, fail_open=True,
            )
        assert result["action"] == "allow"
        assert "fail-open" in result["summary"]
        mock_run.assert_not_called()

    def test_missing_binary_fail_closed(self):
        """When the binary cannot be resolved and fail_open=False, block."""
        from nanobot.agent.tools.tirith_security import check_security

        with patch("nanobot.agent.tools.tirith_security._resolve_tirith_path", return_value=None), \
             patch("subprocess.run") as mock_run:
            result = check_security(
                "ls", enabled=True, tirith_bin="tirith", timeout=5, fail_open=False,
            )
        assert result["action"] == "block"
        assert "fail-closed" in result["summary"]
        mock_run.assert_not_called()


class TestResolveTirithPath:
    """Tests for the _resolve_tirith_path helper."""

    def test_bare_name_uses_path_lookup(self, monkeypatch):
        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/tirith")
        assert _resolve_tirith_path("tirith") == "/usr/bin/tirith"

    def test_explicit_absolute_path_skips_path_lookup(self, monkeypatch, tmp_path):
        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        binpath = tmp_path / "tirith"
        binpath.write_text("")
        binpath.chmod(0o755)
        called = {"which": False}

        def _which(x):
            called["which"] = True
            return None

        monkeypatch.setattr(shutil, "which", _which)
        assert _resolve_tirith_path(str(binpath)) == str(binpath)
        assert called["which"] is False  # explicit path → no PATH lookup

    def test_tilde_expansion(self, monkeypatch, tmp_path):
        import sys

        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        home = tmp_path
        (home / "bin").mkdir()
        binpath = home / "bin" / "tirith"
        binpath.write_text("")
        binpath.chmod(0o755)
        # os.path.expanduser reads HOME on POSIX but USERPROFILE on Windows,
        # so set both to make the test platform-agnostic.
        monkeypatch.setenv("HOME", str(home))
        if sys.platform == "win32":
            monkeypatch.setenv("USERPROFILE", str(home))
        assert _resolve_tirith_path("~/bin/tirith") == str(binpath)

    def test_relative_path_treated_as_explicit(self, monkeypatch, tmp_path):
        """./tirith and bin/tirith must be treated as explicit paths, not PATH lookups."""
        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        binpath = tmp_path / "tirith"
        binpath.write_text("")
        binpath.chmod(0o755)
        monkeypatch.chdir(tmp_path)
        called = {"which": False}

        def _which(x):
            called["which"] = True
            return None

        monkeypatch.setattr(shutil, "which", _which)
        assert _resolve_tirith_path("./tirith") == "./tirith"
        assert called["which"] is False

    def test_directory_is_rejected(self, tmp_path):
        """Directories are traversable (X_OK) but must not resolve as binaries."""
        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        (tmp_path / "some-dir").mkdir()
        assert _resolve_tirith_path(str(tmp_path / "some-dir")) is None

    def test_missing_explicit_path_returns_none(self, tmp_path):
        from nanobot.agent.tools.tirith_security import _resolve_tirith_path

        missing = tmp_path / "does-not-exist" / "tirith"
        assert _resolve_tirith_path(str(missing)) is None
