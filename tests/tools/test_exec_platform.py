"""Tests for cross-platform shell execution.

Verifies that ExecTool selects the correct shell, environment, path-append
strategy, and sandbox behaviour per platform — without actually running
platform-specific binaries (all subprocess calls are mocked).
"""

import asyncio
import shutil
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
        expected = {"HOME", "LANG", "TERM", "PYTHONUNBUFFERED"}
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
        "HOMEPATH", "TEMP", "TMP", "PATHEXT", "PATH", "PYTHONUNBUFFERED",
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
        assert "-l" not in args
        assert "-c" in args
        assert "echo hi" in args

        kwargs = mock_exec.call_args[1]
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL


class TestSpawnWindows:

    @pytest.mark.asyncio
    async def test_single_line_uses_powershell(self):
        """Single-line commands on Windows now route through PowerShell."""
        env = {"COMSPEC": r"C:\Windows\system32\cmd.exe", "PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("dir", r"C:\work", env)

        args = mock_exec.call_args[0]
        assert any(shell in args[0].lower() for shell in ("pwsh", "powershell"))
        assert "-NoProfile" in args
        assert "-NonInteractive" in args
        assert "-Command" in args
        assert "dir" in args[-1]

        kwargs = mock_exec.call_args[1]
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_single_line_passes_cwd_and_env(self):
        """PowerShell should receive cwd and env from the caller."""
        env = {"PATH": "/usr/bin"}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("echo hi", r"C:\work", env)

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == r"C:\work"
        assert kwargs["env"] == env

    @pytest.mark.asyncio
    async def test_multiline_uses_powershell(self):
        env = {"PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn('python -c "print(1)\nprint(2)"', r"C:\work", env)

        args = mock_exec.call_args[0]
        assert any(shell in args[0].lower() for shell in ("pwsh", "powershell"))
        assert "-NoProfile" in args
        assert "-NonInteractive" in args
        assert "-Command" in args
        assert "print(1)" in args[-1]
        assert "print(2)" in args[-1]

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == r"C:\work"
        assert kwargs["env"] == env

    @pytest.mark.asyncio
    async def test_explicit_cmd_shell_uses_raw_shell_string(self):
        """Explicit shell='cmd' should preserve raw cmd.exe quoting semantics."""
        env = {"COMSPEC": r"C:\Windows\system32\cmd.exe", "PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
        ):
            mock_shell.return_value = AsyncMock()
            await ExecTool._spawn(
                'echo "a & b"', r"C:\work", env,
                shell_program=r"C:\Windows\system32\cmd.exe",
            )

        args = mock_shell.call_args[0]
        assert args == ('echo "a & b"',)
        kwargs = mock_shell.call_args[1]
        assert kwargs["cwd"] == r"C:\work"
        assert kwargs["env"] == {
            "COMSPEC": r"C:\Windows\system32\cmd.exe",
            "PATH": "",
        }

    @pytest.mark.asyncio
    async def test_powershell_preserves_last_native_exit_code(self):
        """PowerShell -Command should forward native process exit codes."""
        env = {"PATH": ""}
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("cmd /c exit 7", r"C:\work", env)

        command = mock_exec.call_args[0][-1]
        assert "cmd /c exit 7" in command
        assert "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }" in command

    @pytest.mark.asyncio
    async def test_powershell_invokes_quoted_windows_executable_path(self):
        """PowerShell needs & before quoted executable paths with arguments."""
        env = {"PATH": ""}
        command = r'"D:\Program Files\Python\python.exe" -u -c "print(1)"'
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn(command, r"C:\work", env)

        powershell_command = mock_exec.call_args[0][-1]
        assert powershell_command.startswith("& " + command)

    @pytest.mark.asyncio
    async def test_prefers_pwsh_when_available(self):
        env = {"PATH": ""}

        def fake_which(command):
            if command == "pwsh":
                return r"C:\Program Files\PowerShell\7\pwsh.exe"
            if command == "powershell":
                return r"C:\Windows\system32\WindowsPowerShell\v1.0\powershell.exe"
            return None

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("nanobot.agent.tools.shell.shutil.which", side_effect=fake_which),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("dir", r"C:\work", env)

        args = mock_exec.call_args[0]
        assert "pwsh" in args[0].lower()


# ---------------------------------------------------------------------------
# path_append
# ---------------------------------------------------------------------------

class TestPathAppendPlatform:

    @pytest.mark.asyncio
    async def test_unix_uses_env_var_in_fixed_export(self):
        """On Unix, path_append must not be interpolated into shell source."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=True):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_append="/opt/bin; echo INJECTED")
            await tool.execute(command="ls")

        assert captured_cmd == 'export PATH="$PATH:$NANOBOT_PATH_APPEND"; ls'
        assert captured_env["NANOBOT_PATH_APPEND"] == "/opt/bin; echo INJECTED"
        assert "INJECTED" not in captured_cmd

    @pytest.mark.asyncio
    async def test_unix_path_prepend_uses_env_var_in_fixed_export(self):
        """On Unix, path_prepend must not be interpolated into shell source."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=True, *, stdin=None):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_prepend="/venv/bin; echo INJECTED")
            await tool.execute(command="python --version")

        assert captured_cmd == 'export PATH="$NANOBOT_PATH_PREPEND:$PATH"; python --version'
        assert captured_env["NANOBOT_PATH_PREPEND"] == "/venv/bin; echo INJECTED"
        assert "INJECTED" not in captured_cmd

    @pytest.mark.asyncio
    async def test_unix_path_prepend_and_append_order(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=True, *, stdin=None):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_prepend="/venv/bin", path_append="/usr/sbin")
            await tool.execute(command="python --version")

        assert captured_cmd == (
            'export PATH="$NANOBOT_PATH_PREPEND:$PATH:$NANOBOT_PATH_APPEND"; python --version'
        )
        assert captured_env["NANOBOT_PATH_PREPEND"] == "/venv/bin"
        assert captured_env["NANOBOT_PATH_APPEND"] == "/usr/sbin"

    @pytest.mark.asyncio
    async def test_windows_modifies_env(self):
        """On Windows, path_append is appended to PATH in the env dict."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_env = {}

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=True):
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("nanobot.agent.tools.shell.os.pathsep", ";"),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_append=r"C:\tools\bin")
            await tool.execute(command="dir")

        assert captured_env["PATH"].endswith(r";C:\tools\bin")

    @pytest.mark.asyncio
    async def test_windows_path_prepend_and_append_order(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        captured_env = {}

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=True, *, stdin=None):
            captured_env.update(env)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("nanobot.agent.tools.shell.os.pathsep", ";"),
            patch.object(ExecTool, "_build_env", return_value={"PATH": r"C:\Windows\System32"}),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_prepend=r"C:\venv\Scripts", path_append=r"C:\tools\bin")
            await tool.execute(command="python --version")

        assert captured_env["PATH"] == (
            r"C:\venv\Scripts;C:\Windows\System32;C:\tools\bin"
        )


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

    @pytest.mark.asyncio
    async def test_execute_defaults_to_non_login_shell(self):
        """The public execute path must not silently request a login shell."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok\n", b"")
        mock_proc.returncode = 0
        captured_login = []

        async def capture_spawn(cmd, cwd, env, shell_program=None, login=None, *, stdin=None):
            captured_login.append(login)
            return mock_proc

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            await tool.execute(command="echo ok")
            await tool.execute(command="echo ok", login=True)

        assert captured_login == [False, True]


# ---------------------------------------------------------------------------
# _extract_absolute_paths - UNC path support
# ---------------------------------------------------------------------------

class TestExtractAbsolutePaths:
    """Tests for Windows UNC path extraction in shell commands."""

    def test_windows_drive_path(self):
        """Test extraction of standard Windows drive paths."""
        cmd = r"dir C:\Users\Public"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"C:\Users\Public" in paths

    def test_windows_drive_path_root(self):
        """Test extraction of Windows drive root paths."""
        cmd = r"dir C:\temp"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert any("C:\\" in p for p in paths)

    def test_unc_path_simple(self):
        """Test extraction of simple UNC paths."""
        cmd = r"dir \\server\share"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share" in paths

    def test_unc_path_with_subdirs(self):
        """Test extraction of UNC paths with subdirectories."""
        cmd = r"copy \\server\share\folder\file.txt D:\backup"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share\folder\file.txt" in paths
        assert r"D:\backup" in paths

    def test_unc_path_in_quotes(self):
        """Test extraction of UNC paths enclosed in quotes."""
        cmd = r'type "\\server\share\docs\readme.txt"'
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share\docs\readme.txt" in paths

    def test_mixed_paths(self):
        """Test extraction of mixed UNC, drive, and POSIX paths."""
        cmd = r'copy \\server\data\file.txt C:\local\temp && ls /tmp'
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\data\file.txt" in paths
        assert any("C:\\" in p for p in paths)
        assert "/tmp" in paths

    def test_home_path(self):
        """Test extraction of home directory shortcuts."""
        cmd = "cat ~/config.txt"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert "~/config.txt" in paths

    def test_no_paths(self):
        """Test command with no absolute paths."""
        cmd = "echo hello"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert paths == []


# ---------------------------------------------------------------------------
# Windows multi-line command PowerShell fallback
# ---------------------------------------------------------------------------

class TestWindowsMultilineExec:
    """Verify commands on Windows route through PowerShell (now the default)."""

    @pytest.mark.asyncio
    async def test_multiline_python_uses_powershell(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n2\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            mock_exec.return_value = mock_proc
            tool = ExecTool()
            result = await tool.execute(command='python -c "print(1)\nprint(2)"')

        assert "1" in result
        assert "2" in result
        assert "Exit code: 0" in result
        args = mock_exec.call_args[0]
        assert any(shell in args[0].lower() for shell in ("pwsh", "powershell"))

    @pytest.mark.asyncio
    async def test_multiline_node_uses_powershell(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            mock_exec.return_value = mock_proc
            tool = ExecTool()
            result = await tool.execute(command='node -e "console.log(1)\nconsole.log(2)"')

        assert "1" in result
        args = mock_exec.call_args[0]
        assert any(shell in args[0].lower() for shell in ("pwsh", "powershell"))

    @pytest.mark.asyncio
    async def test_single_line_uses_powershell(self):
        """Single-line commands also route through PowerShell now."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.object(ExecTool, "_spawn", return_value=mock_proc) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command='python -c "print(1)"')

        assert "1" in result
        mock_spawn.assert_called_once()

    @pytest.mark.asyncio
    async def test_unix_unchanged(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n2\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.object(ExecTool, "_spawn", return_value=mock_proc) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command='python -c "print(1)\nprint(2)"')

        assert "1" in result
        mock_spawn.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_shell — Windows support
# ---------------------------------------------------------------------------

class TestResolveShellWindows:
    """shell parameter is now accepted on Windows."""

    @pytest.mark.asyncio
    async def test_shell_powershell_accepted(self):
        """shell='powershell' should resolve and route through PowerShell."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            mock_exec.return_value = mock_proc
            tool = ExecTool()
            result = await tool.execute(command="echo hello", shell="powershell")

        assert "hello" in result
        args = mock_exec.call_args[0]
        assert "powershell" in args[0].lower()
        assert "-NonInteractive" in args

    @pytest.mark.asyncio
    async def test_shell_cmd_accepted(self):
        """shell='cmd' should preserve the command string for cmd.exe parsing."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b'"a & b"\n', b"")
        mock_proc.returncode = 0

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            mock_shell.return_value = mock_proc
            tool = ExecTool()
            result = await tool.execute(command='echo "a & b"', shell="cmd")

        assert '"a & b"' in result
        args = mock_shell.call_args[0]
        assert args == ('echo "a & b"',)

    @pytest.mark.asyncio
    async def test_shell_bash_rejected_on_windows(self):
        """shell='bash' should still be rejected on Windows."""
        with patch("nanobot.agent.tools.shell._IS_WINDOWS", True):
            tool = ExecTool()
            result = await tool.execute(command="echo hello", shell="bash")

        assert "Error: unsupported shell" in result
        assert "Allowed: powershell, pwsh, cmd" in result


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="requires Windows",
)
class TestWindowsRealExec:

    @pytest.mark.skipif(shutil.which("pwsh") is None, reason="requires PowerShell 7")
    @pytest.mark.asyncio
    async def test_single_line_and_separator_uses_pwsh(self):
        result = await ExecTool(timeout=10).execute(command="echo before && echo after")

        assert "before" in result
        assert "after" in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_explicit_cmd_preserves_embedded_quotes(self):
        result = await ExecTool(timeout=10).execute(command='echo "a & b"', shell="cmd")

        assert '"a & b"' in result
        assert r'\"a & b\"' not in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_default_powershell_preserves_native_exit_code(self):
        result = await ExecTool(timeout=10).execute(command="cmd /c exit 7")

        assert "Exit code: 7" in result
