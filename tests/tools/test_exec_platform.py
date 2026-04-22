"""Tests for cross-platform shell execution.

Verifies that ExecTool selects the correct shell, environment, path-append
strategy, and sandbox behaviour per platform — without actually running
platform-specific binaries (all subprocess calls are mocked).
"""

import sys
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.tools.shell import ExecTool

_WINDOWS_ENV_KEYS = {
    "APPDATA", "LOCALAPPDATA", "ProgramData",
    "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
}


# ---------------------------------------------------------------------------
# _build_env
# ---------------------------------------------------------------------------

class TestBuildEnvUnix:

    def test_expected_keys(self):
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", False):
            env = ExecTool()._build_env()
        expected = {"HOME", "LANG", "PATH","TERM"}
        assert expected <= set(env)
        if sys.platform != "win32":
            assert set(env) == expected

    def test_home_from_environ(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/dev")
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", False):
            env = ExecTool()._build_env()
        assert env["HOME"] == "/Users/dev"

    def test_secrets_excluded(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
        monkeypatch.setenv("NANOBOT_TOKEN", "tok-secret")
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", False):
            env = ExecTool()._build_env()
        assert "OPENAI_API_KEY" not in env
        assert "NANOBOT_TOKEN" not in env
        for v in env.values():
            assert "secret" not in v.lower()


class TestBuildEnvWindows:

    _EXPECTED_KEYS = {
        "SYSTEMROOT", "COMSPEC", "USERPROFILE", "HOMEDRIVE",
        "HOMEPATH", "TEMP", "TMP", "PATHEXT", "PATH",
        *_WINDOWS_ENV_KEYS,
    }

    def test_expected_keys(self):
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", True):
            env = ExecTool()._build_env()
        assert set(env) == self._EXPECTED_KEYS

    def test_secrets_excluded(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
        monkeypatch.setenv("NANOBOT_TOKEN", "tok-secret")
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", True):
            env = ExecTool()._build_env()
        assert "OPENAI_API_KEY" not in env
        assert "NANOBOT_TOKEN" not in env
        for v in env.values():
            assert "secret" not in v.lower()

    def test_path_has_sensible_default(self):
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = ExecTool()._build_env()
        assert "system32" in env["PATH"].lower()

    def test_systemroot_forwarded(self, monkeypatch):
        monkeypatch.setenv("SYSTEMROOT", r"D:\Windows")
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", True):
            env = ExecTool()._build_env()
        assert env["SYSTEMROOT"] == r"D:\Windows"


# ---------------------------------------------------------------------------
# _spawn
# ---------------------------------------------------------------------------

class TestSpawnUnix:

    @pytest.mark.asyncio
    async def test_uses_bash(self):
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("echo hi", "/tmp", {"HOME": "/tmp"})

        args = mock_exec.call_args[0]
        assert "bash" in args[0]
        assert "-l" in args
        assert "-c" in args
        assert "echo hi" in args


class TestSpawnWindows:

    @pytest.mark.asyncio
    async def test_uses_comspec_from_env(self):
        env = {"COMSPEC": r"C:\Windows\system32\cmd.exe", "PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("dir", r"C:\Users", env)

        args = mock_exec.call_args[0]
        assert "cmd.exe" in args[0]
        assert "/c" in args
        assert "dir" in args

    @pytest.mark.asyncio
    async def test_falls_back_to_default_comspec(self):
        env = {"PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.dict("os.environ", {}, clear=True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("dir", r"C:\Users", env)

        args = mock_exec.call_args[0]
        assert args[0] == "cmd.exe"


# ---------------------------------------------------------------------------
# path_append
# ---------------------------------------------------------------------------

class TestPathAppendPlatform:

    @pytest.mark.asyncio
    async def test_unix_injects_export (self):
        """On Unix, path_append is passed via the env dict, not shell string."""
        mock_proc = AsyncMock ()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_cmd = None
        captured_env = {}

        async def capture_spawn (cmd, cwd, env):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update (env)
            return mock_proc

        with (
            patch ("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch ("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object (ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object (ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool (path_append="/opt/bin")
            await tool.execute (command="ls")

        # path_append must be in the env dict, NOT injected into the command
        assert captured_cmd == "ls"
        assert captured_env["PATH"].endswith (":/opt/bin")

    @pytest.mark.asyncio
    async def test_windows_modifies_env(self):
        """On Windows, path_append is appended to PATH in the env dict."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_env = {}

        async def capture_spawn(cmd, cwd, env):
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch ("nanobot.agent.tools.shell.os.pathsep", ";"),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_append=r"C:\tools\bin")
            await tool.execute(command="dir")

        assert captured_env["PATH"].endswith(r";C:\tools\bin")


# ---------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------

class TestSandboxPlatform:

    @pytest.mark.asyncio
    async def test_bwrap_skipped_on_windows(self):
        """bwrap must be silently skipped on Windows, not crash."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.object(ExecTool, "_spawn", return_value=mock_proc) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(sandbox="bwrap")
            result = await tool.execute(command="dir")

        assert "ok" in result
        spawned_cmd = mock_spawn.call_args[0][0]
        assert "bwrap" not in spawned_cmd

    @pytest.mark.asyncio
    async def test_bwrap_applied_on_unix(self):
        """On Unix, sandbox wrapping should still happen normally."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"sandboxed", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.wrap_command", return_value="bwrap -- sh -c ls") as mock_wrap,
            patch.object(ExecTool, "_spawn", return_value=mock_proc) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(sandbox="bwrap", working_dir="/workspace")
            await tool.execute(command="ls")

        mock_wrap.assert_called_once()
        spawned_cmd = mock_spawn.call_args[0][0]
        assert "bwrap" in spawned_cmd


# ---------------------------------------------------------------------------
# end-to-end (mocked subprocess, full execute path)
# ---------------------------------------------------------------------------

class TestExecuteEndToEnd:

    @pytest.mark.asyncio
    async def test_windows_full_path(self):
        """Full execute() flow on Windows: env, spawn, output formatting."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello world\r\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.object(ExecTool, "_spawn", return_value=mock_proc),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command="echo hello world")

        assert "hello world" in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_unix_full_path(self):
        """Full execute() flow on Unix: env, spawn, output formatting."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello world\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.object(ExecTool, "_spawn", return_value=mock_proc),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command="echo hello world")

        assert "hello world" in result
        assert "Exit code: 0" in result
