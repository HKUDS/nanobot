"""Tests for cross-platform shell execution.

Verifies that ExecTool selects the correct shell, environment, path-append
strategy, and sandbox behaviour per platform — without actually running
platform-specific binaries (all subprocess calls are mocked).
"""

import asyncio
import os
import re
import shutil
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.execution import processes

_WINDOWS_ENV_KEYS = {
    "APPDATA", "LOCALAPPDATA", "ProgramData",
    "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
}


class _CompletedProcess:
    """A finished subprocess with the stream/wait protocol used by the collector."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.pid = 12345
        self.returncode = returncode
        self.stdin = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()

    async def wait(self) -> int:
        await asyncio.sleep(0)
        return self.returncode


class _FakeWindowsJob:
    creation_flags = 0

    def assign_and_resume(self, pid: int) -> None:
        pass

    def release(self) -> None:
        pass

    def terminate(self) -> None:
        pass


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


class TestArgumentVectorPath:

    def test_uses_parent_path_for_executable_lookup(self):
        parent_path = os.pathsep.join(("parent-bin", "system-bin"))
        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.dict(
                "os.environ",
                {"PATH": parent_path, "NANOBOT_SECRET_TOKEN": "super-secret-value"},
                clear=True,
            ),
        ):
            prepared = ExecTool()._prepare_command(["rg", "--version"])

        assert not isinstance(prepared, str)
        assert prepared.env["PATH"] == parent_path
        assert "NANOBOT_SECRET_TOKEN" not in prepared.env


class TestSpawnUnix:

    @pytest.mark.asyncio
    async def test_uses_bash(self):
        with (
            patch.object(processes, "_IS_WINDOWS", False),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("echo hi", "/tmp", {"HOME": "/tmp"})

        args = mock_exec.call_args[0]
        assert "bash" in args[0]
        assert "-l" not in args
        assert "-c" in args
        assert "echo hi" in args

        kwargs = mock_exec.call_args[1]
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_process_tree_starts_new_session(self):
        with (
            patch.object(processes, "_IS_WINDOWS", False),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree(
                "echo hi",
                "/tmp",
                {"HOME": "/tmp"},
            )

        assert mock_exec.call_args.kwargs["start_new_session"] is True


class TestSpawnWindows:
    @pytest.fixture(autouse=True)
    def windows_launcher(self, monkeypatch):
        monkeypatch.setattr(processes, "_IS_WINDOWS", True)
        monkeypatch.setattr(processes, "_create_windows_job", _FakeWindowsJob)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("command", "shell_program"), [
        ("echo hi", None),
        ("echo hi", "cmd"),
        ([sys.executable, "--version"], None),
    ])
    async def test_job_assignment_failure_kills_suspended_process(self, command, shell_program):
        env = {"PATH": ""}
        process = AsyncMock()
        process.pid = 123
        process.returncode = None
        process.kill = MagicMock()
        process.wait.return_value = -9
        job = MagicMock(spec=_FakeWindowsJob)
        job.creation_flags = 0x4
        job.assign_and_resume.side_effect = OSError("OpenProcess failed")

        with (
            patch("asyncio.create_subprocess_exec", return_value=process) as mock_exec,
            patch("asyncio.create_subprocess_shell", return_value=process) as mock_shell,
            patch.object(processes, "_create_windows_job", return_value=job),
            pytest.raises(OSError, match="OpenProcess failed"),
        ):
            await processes.spawn_process_tree(command, r"C:\work", env, shell_program)

        launcher = mock_shell if shell_program == "cmd" else mock_exec
        assert launcher.call_args.kwargs["creationflags"] == job.creation_flags
        job.assign_and_resume.assert_called_once_with(process.pid)
        job.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_single_line_uses_powershell(self):
        env = {"COMSPEC": r"C:\Windows\system32\cmd.exe", "PATH": ""}
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("dir", r"C:\work", env)

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
        env = {"PATH": "/usr/bin"}
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("echo hi", r"C:\work", env)

        kwargs = mock_exec.call_args[1]
        assert kwargs["cwd"] == r"C:\work"
        assert kwargs["env"] == env

    @pytest.mark.asyncio
    async def test_multiline_uses_powershell(self):
        env = {"PATH": ""}
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree('python -c "print(1)\nprint(2)"', r"C:\work", env)

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
        env = {"COMSPEC": r"C:\Windows\system32\cmd.exe", "PATH": ""}
        with (
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
        ):
            mock_shell.return_value = AsyncMock()
            await processes.spawn_process_tree(
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
        env = {"PATH": ""}
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("cmd /c exit 7", r"C:\work", env)

        command = mock_exec.call_args[0][-1]
        assert "cmd /c exit 7" in command
        assert "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }" in command

    @pytest.mark.asyncio
    async def test_powershell_configures_utf8_io(self):
        env = {"PATH": ""}
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("Write-Output 'café 你好'", r"C:\work", env)

        command = mock_exec.call_args[0][-1]
        assert "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)" in command
        assert (
            "if ($PSVersionTable.PSVersion.Major -lt 6) { "
            "$OutputEncoding = [Console]::OutputEncoding }"
        ) in command
        assert "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'" in command

    @pytest.mark.asyncio
    async def test_powershell_invokes_quoted_windows_executable_path(self):
        env = {"PATH": ""}
        command = r'"D:\Program Files\Python\python.exe" -u -c "print(1)"'
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree(command, r"C:\work", env)

        powershell_command = mock_exec.call_args[0][-1]
        assert f"\n& {command}\n" in powershell_command

    @pytest.mark.asyncio
    async def test_powershell_invokes_quoted_windows_executable_without_arguments(self):
        env = {"PATH": ""}
        command = r'"D:\Program Files\Git\cmd\git.exe"'
        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree(command, r"C:\work", env)

        powershell_command = mock_exec.call_args[0][-1]
        assert f"\n& {command}\n" in powershell_command

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
            patch.object(processes.shutil, "which", side_effect=fake_which),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await processes.spawn_process_tree("dir", r"C:\work", env)

        args = mock_exec.call_args[0]
        assert "pwsh" in args[0].lower()


class TestPathAppendPlatform:

    @pytest.mark.asyncio
    async def test_unix_uses_env_var_in_fixed_export(self):
        mock_proc = _CompletedProcess(b"ok")

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=True, *, stdin=None,
        ):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return processes.ProcessTree(mock_proc)

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_append="/opt/bin; echo INJECTED")
            await tool.execute(command="ls")

        assert captured_cmd == 'export PATH="$PATH:$NANOBOT_PATH_APPEND"; ls'
        assert captured_env["NANOBOT_PATH_APPEND"] == "/opt/bin; echo INJECTED"
        assert "INJECTED" not in captured_cmd

    @pytest.mark.asyncio
    async def test_unix_path_prepend_uses_env_var_in_fixed_export(self):
        mock_proc = _CompletedProcess(b"ok")

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=True, *, stdin=None,
        ):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return processes.ProcessTree(mock_proc)

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_prepend="/venv/bin; echo INJECTED")
            await tool.execute(command="python --version")

        assert captured_cmd == 'export PATH="$NANOBOT_PATH_PREPEND:$PATH"; python --version'
        assert captured_env["NANOBOT_PATH_PREPEND"] == "/venv/bin; echo INJECTED"
        assert "INJECTED" not in captured_cmd

    @pytest.mark.asyncio
    async def test_unix_path_prepend_and_append_order(self):
        mock_proc = _CompletedProcess(b"ok")

        captured_cmd = None
        captured_env = {}

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=True, *, stdin=None,
        ):
            nonlocal captured_cmd
            captured_cmd = cmd
            captured_env.update(env)
            return processes.ProcessTree(mock_proc)

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.agent.tools.shell.os.pathsep", ":"),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
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
        mock_proc = _CompletedProcess(b"ok")

        captured_env = {}

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=True, *, stdin=None,
        ):
            captured_env.update(env)
            return processes.ProcessTree(mock_proc)

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("nanobot.agent.tools.shell.os.pathsep", ";"),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_append=r"C:\tools\bin")
            await tool.execute(command="dir")

        assert captured_env["PATH"].endswith(r";C:\tools\bin")

    @pytest.mark.asyncio
    async def test_windows_path_prepend_and_append_order(self):
        mock_proc = _CompletedProcess(b"ok")

        captured_env = {}

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=True, *, stdin=None,
        ):
            captured_env.update(env)
            return processes.ProcessTree(mock_proc)

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("nanobot.agent.tools.shell.os.pathsep", ";"),
            patch.object(ExecTool, "_build_env", return_value={"PATH": r"C:\Windows\System32"}),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(path_prepend=r"C:\venv\Scripts", path_append=r"C:\tools\bin")
            await tool.execute(command="python --version")

        assert captured_env["PATH"] == (
            r"C:\venv\Scripts;C:\Windows\System32;C:\tools\bin"
        )


class TestSandboxPlatform:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("backend", ["bwrap", "seatbelt"])
    async def test_sandbox_skipped_on_windows(self, backend):
        mock_proc = _CompletedProcess(b"ok")

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.object(processes, "spawn_process_tree", return_value=processes.ProcessTree(mock_proc)) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(sandbox=backend)
            result = await tool.execute(command="dir")

        assert "ok" in result
        spawned_cmd = mock_spawn.call_args[0][0]
        assert backend not in spawned_cmd

    @pytest.mark.asyncio
    @pytest.mark.parametrize("backend", ["bwrap", "seatbelt"])
    async def test_unix_sandbox_launch_uses_trusted_launcher_and_configured_binds(self, tmp_path, backend):
        mock_proc = _CompletedProcess(b"sandboxed")
        trusted_bin = tmp_path / "trusted-bin"
        launcher = trusted_bin / ("bwrap" if backend == "bwrap" else "sandbox-exec")
        workspace = tmp_path / "project"
        tool_bin = tmp_path / "tool-bin"
        tool_cache = tmp_path / "tool-cache"

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("nanobot.execution.sandbox.resolve_sandbox_launcher", return_value=str(launcher)),
            patch.object(processes, "spawn_process_tree", return_value=processes.ProcessTree(mock_proc)) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool(
                sandbox=backend,
                working_dir=str(workspace),
                sandbox_ro_binds=[str(tool_bin)],
                sandbox_rw_binds=[str(tool_cache)],
            )
            result = await tool.execute(command="ls")

        assert "sandboxed" in result
        command, cwd, *_ = mock_spawn.call_args.args
        assert isinstance(command, list)
        assert command[0] == str(launcher)
        assert cwd == str(workspace.resolve())
        if backend == "bwrap":
            assert command[-9:-3] == [
                "--bind-try", str(tool_cache.resolve()), str(tool_cache.resolve()),
                "--chdir", cwd, "--",
            ]
            assert command[-12:-9] == [
                "--ro-bind-try", str(tool_bin.resolve()), str(tool_bin.resolve()),
            ]
        else:
            profile = command[2]
            ro = str(tool_bin.resolve()).replace("\\", "\\\\")
            rw = str(tool_cache.resolve()).replace("\\", "\\\\")
            assert f'(deny file-write* (subpath "{ro}"))' in profile
            assert f'(allow file-read* file-write* (subpath "{rw}"))' in profile


class TestExecuteEndToEnd:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "yield_time_ms, stdin",
        [(None, asyncio.subprocess.DEVNULL), (1000, asyncio.subprocess.PIPE)],
    )
    async def test_windows_full_path(self, yield_time_ms, stdin):
        mock_proc = _CompletedProcess(b"hello world\r\n")
        job = MagicMock(spec=_FakeWindowsJob)
        job.creation_flags = 0x4

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch.object(processes, "_IS_WINDOWS", True),
            patch.object(processes, "_create_windows_job", return_value=job),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command="echo hello world", yield_time_ms=yield_time_ms)

        assert "hello world" in result
        assert "Exit code: 0" in result
        assert "session_id:" not in result
        assert mock_exec.call_args.kwargs["stdin"] == stdin
        job.assign_and_resume.assert_called_once_with(mock_proc.pid)
        job.release.assert_called_once_with()
        job.terminate.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "yield_time_ms, stdin",
        [(None, asyncio.subprocess.DEVNULL), (1000, asyncio.subprocess.PIPE)],
    )
    async def test_unix_full_path(self, yield_time_ms, stdin):
        mock_proc = _CompletedProcess(b"hello world\n")

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.object(processes, "spawn_process_tree", return_value=processes.ProcessTree(mock_proc)) as mock_spawn,
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            result = await tool.execute(command="echo hello world", yield_time_ms=yield_time_ms)

        assert "hello world" in result
        assert "Exit code: 0" in result
        assert "session_id:" not in result
        assert mock_spawn.call_args.kwargs.get("stdin", asyncio.subprocess.DEVNULL) == stdin

    @pytest.mark.asyncio
    async def test_execute_defaults_to_non_login_shell(self):
        captured_login = []

        async def capture_spawn(
            cmd, cwd, env, shell_program=None, login=None, *, stdin=None,
        ):
            captured_login.append(login)
            return processes.ProcessTree(_CompletedProcess(b"ok\n"))

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch.object(processes, "spawn_process_tree", side_effect=capture_spawn),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            tool = ExecTool()
            await tool.execute(command="echo ok")
            await tool.execute(command="echo ok", login=True)

        assert captured_login == [False, True]


class TestExtractAbsolutePaths:

    def test_windows_drive_path(self):
        cmd = r"dir C:\Users\Public"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"C:\Users\Public" in paths

    def test_windows_drive_path_root(self):
        cmd = r"dir C:\temp"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert any("C:\\" in p for p in paths)

    def test_unc_path_simple(self):
        cmd = r"dir \\server\share"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share" in paths

    def test_unc_path_with_subdirs(self):
        cmd = r"copy \\server\share\folder\file.txt D:\backup"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share\folder\file.txt" in paths
        assert r"D:\backup" in paths

    def test_unc_path_in_quotes(self):
        cmd = r'type "\\server\share\docs\readme.txt"'
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\share\docs\readme.txt" in paths

    def test_mixed_paths(self):
        cmd = r'copy \\server\data\file.txt C:\local\temp && ls /tmp'
        paths = ExecTool._extract_absolute_paths(cmd)
        assert r"\\server\data\file.txt" in paths
        assert any("C:\\" in p for p in paths)
        assert "/tmp" in paths

    def test_home_path(self):
        cmd = "cat ~/config.txt"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert "~/config.txt" in paths

    def test_no_paths(self):
        cmd = "echo hello"
        paths = ExecTool._extract_absolute_paths(cmd)
        assert paths == []


class TestWindowsMultilineExec:

    @pytest.mark.asyncio
    async def test_multiline_python_uses_powershell(self):
        mock_proc = _CompletedProcess(b"1\n2\n")

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(processes, "_IS_WINDOWS", True),
            patch.object(processes, "_create_windows_job", side_effect=_FakeWindowsJob),
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
        mock_proc = _CompletedProcess(b"1\n")

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(processes, "_IS_WINDOWS", True),
            patch.object(processes, "_create_windows_job", side_effect=_FakeWindowsJob),
            patch.object(ExecTool, "_guard_command", return_value=None),
        ):
            mock_exec.return_value = mock_proc
            tool = ExecTool()
            result = await tool.execute(command='node -e "console.log(1)\nconsole.log(2)"')

        assert "1" in result
        args = mock_exec.call_args[0]
        assert any(shell in args[0].lower() for shell in ("pwsh", "powershell"))

class TestResolveShellWindows:

    @pytest.mark.asyncio
    async def test_shell_powershell_accepted(self):
        mock_proc = _CompletedProcess(b"hello\n")

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch.object(processes, "_IS_WINDOWS", True),
            patch.object(processes, "_create_windows_job", side_effect=_FakeWindowsJob),
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
        mock_proc = _CompletedProcess(b'"a & b"\n')

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", True),
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
            patch.object(processes, "_IS_WINDOWS", True),
            patch.object(processes, "_create_windows_job", side_effect=_FakeWindowsJob),
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

    async def _execute(self, command, shell=None, **kwargs):
        manager = ExecSessionManager()
        try:
            initial = await ExecTool(session_manager=manager, **kwargs).execute(command=command, shell=shell)
            match = re.search(r"session_id:\s*([0-9a-f]+)", initial)
            if match is None:
                return initial
            final = await ExecSessionTool(manager=manager).execute(
                session_id=match.group(1), until_exit=True,
            )
            return initial + "\n" + final
        finally:
            await manager.close_all()

    @pytest.mark.skipif(shutil.which("pwsh") is None, reason="requires PowerShell 7")
    @pytest.mark.asyncio
    async def test_single_line_and_separator_uses_pwsh(self):
        result = await self._execute(command="echo before && echo after", timeout=10)

        assert "before" in result
        assert "after" in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_explicit_cmd_preserves_embedded_quotes(self):
        result = await self._execute(command='echo "a & b"', shell="cmd", timeout=10)

        assert '"a & b"' in result
        assert r'\"a & b\"' not in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_default_powershell_preserves_native_exit_code(self):
        result = await self._execute(command="cmd /c exit 7", timeout=10)

        assert "Exit code: 7" in result

    @pytest.mark.asyncio
    async def test_windows_powershell_output_and_redirection_are_utf8(self, tmp_path):
        result = await self._execute(
            working_dir=str(tmp_path), timeout=180,
            command=(
                "Write-Output 'file café λ 你好' > marker.txt; "
                "Write-Output 'café λ 你好'; "
                "[Console]::Error.WriteLine('warn λ 你好')"
            ),
            shell="powershell",
        )

        assert "café λ 你好" in result
        assert "warn λ 你好" in result
        assert "\x00" not in result
        assert "Exit code: 0" in result

        data = (tmp_path / "marker.txt").read_bytes()
        assert b"\x00" not in data
        assert data.decode("utf-8-sig").strip() == "file café λ 你好"

    @pytest.mark.asyncio
    async def test_windows_powershell_native_pipeline_input_is_utf8(self):
        python = sys.executable.replace("'", "''")
        result = await self._execute(
            timeout=180,
            command=(
                f"[string][char]0x4F1A | & '{python}' "
                '-c "import sys; print(sys.stdin.buffer.read().hex())"'
            ),
            shell="powershell",
        )

        assert "e4bc9a0d0a" in result
        assert "Exit code: 0" in result

    @pytest.mark.asyncio
    async def test_windows_powershell_session_output_is_utf8(self):
        manager = ExecSessionManager()
        try:
            result = await ExecTool(timeout=180, session_manager=manager).execute(
                command="Start-Sleep -Milliseconds 1500; Write-Output 'café λ 你好'",
                shell="powershell",
                yield_time_ms=1000,
            )

            if "session_id:" in result:
                session_id = result.split("session_id:", 1)[1].splitlines()[0].strip()
                poll_result = await ExecSessionTool(manager=manager).execute(
                    session_id=session_id,
                    input="",
                    wait_for="café λ 你好",
                    timeout_ms=120_000,
                )
                result += "\n" + poll_result
                if "Process running." in poll_result:
                    final_result = await ExecSessionTool(manager=manager).execute(
                        session_id=session_id,
                        input="",
                        timeout_ms=30_000,
                    )
                    result += "\n" + final_result
                    assert "Process running." not in final_result

            assert "café λ 你好" in result
            assert "Exit code: 0" in result
            assert "\x00" not in result
        finally:
            await manager.close_all()
