"""Regression coverage for nonstandard sandbox launcher installations."""

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.sandbox_check import check_sandbox, sandbox_settings_status
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.shell_config import ExecToolConfig
from nanobot.config.loader import resolve_config_env_vars
from nanobot.security.sandbox_launcher import SandboxLauncherError, resolve_sandbox_launcher


@pytest.mark.skipif(os.name != "posix", reason="requires Unix launcher preparation")
async def test_nonstandard_bwrap_is_not_silently_run_without_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    extra_bin = tmp_path / "extra-bin"
    extra_bin.mkdir()
    default_bin = tmp_path / "system-bin"
    default_bin.mkdir()
    launcher = extra_bin / "bwrap"
    launcher.write_text("#!/bin/sh\nprintf launched > launcher-ran\n")
    launcher.chmod(0o700)
    marker = workspace / "command-ran"

    monkeypatch.setattr(os, "defpath", str(default_bin))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(extra_bin))
    monkeypatch.setattr("nanobot.execution.sandbox.get_media_dir", lambda: workspace)
    tool = ExecTool(working_dir=str(workspace), sandbox="bwrap")

    result = await tool.execute(command="printf ran > command-ran")

    assert "sandbox launcher not found: bwrap" in result
    assert isinstance(result, ToolResult) and result.error_code == "sandbox_launcher_missing"
    status = await check_sandbox(ExecToolConfig(sandbox="bwrap"), workspace)
    assert status["state"] == "unavailable"
    assert status["reason"] == "launcher_missing"
    assert not (workspace / "launcher-ran").exists()
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="Unix protected launcher permissions")
@pytest.mark.parametrize("location", ["workspace", "apphome"])
async def test_writable_custom_launcher_is_rejected_before_execution(tmp_path, location):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    installation = workspace if location == "workspace" else tmp_path / "apphome" / "nanobot" / "bin"
    installation.mkdir(parents=True, exist_ok=True)
    launcher = installation / "bwrap"
    marker = tmp_path / "launcher-ran"
    launcher.write_text(f"#!/bin/sh\ntouch {marker}\n")
    launcher.chmod(0o755)
    config = ExecToolConfig(sandbox="bwrap", sandbox_launcher=str(launcher))
    # Rejection is independent of the selected shell and PATH.
    tool = ExecTool(working_dir=str(workspace), sandbox="bwrap", sandbox_launcher=str(launcher))
    response = await tool.execute(command="echo command-ran", shell="/bin/sh", login=True)
    assert "sandbox launcher rejected" in response
    assert isinstance(response, ToolResult) and response.error_code in {
        "sandbox_agent_writable", "sandbox_unprotected_installation",
    }
    assert not marker.exists()
    if sys.platform.startswith("linux"):
        status = await check_sandbox(config, workspace)
        assert status["state"] == "unavailable"
        assert status["reason"] in {"agent_writable", "unprotected_installation"}
        assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="Unix protected launcher permissions")
def test_root_owned_override_and_expanded_writable_bind(monkeypatch):
    launcher = Path("/bin/sh").resolve()
    assert resolve_sandbox_launcher("bwrap", str(launcher)) == str(launcher)
    monkeypatch.setenv("SANDBOX_TEST_BIND", str(launcher.parent))
    with pytest.raises(SandboxLauncherError, match="agent_writable"):
        resolve_sandbox_launcher("bwrap", str(launcher), writable_roots=(Path("$SANDBOX_TEST_BIND"),))


@pytest.mark.skipif(os.name != "posix", reason="Unix absolute paths")
@pytest.mark.parametrize("path,reason", [("bin/bwrap", "path_not_absolute"), ("/nonexistent-nanobot-launcher", "path_unavailable")])
def test_custom_launcher_requires_existing_absolute_file(path, reason):
    with pytest.raises(SandboxLauncherError, match=reason):
        resolve_sandbox_launcher("bwrap", path)


def test_copied_custom_launcher_config_does_not_assume_unix_permissions_on_windows(monkeypatch):
    monkeypatch.setattr("nanobot.security.sandbox_launcher.os", SimpleNamespace(name="nt"))
    with pytest.raises(SandboxLauncherError, match="platform_unsupported"):
        resolve_sandbox_launcher("bwrap", "C:\\tools\\bwrap.exe")


@pytest.mark.parametrize("settings,state", [({"enable": False}, "disabled"), ({}, "off")])
async def test_disabled_settings_do_not_launch_a_probe(settings, state, tmp_path, monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("disabled sandbox must not start a process")
    monkeypatch.setattr("asyncio.create_subprocess_exec", unexpected)
    assert (await check_sandbox(ExecToolConfig(**settings), tmp_path))["state"] == state


@pytest.mark.parametrize(("platform", "backend", "supported"), [
    ("win32", "bwrap", None),
    ("linux", "seatbelt", "bwrap"),
    ("darwin", "bwrap", "seatbelt"),
])
async def test_unsupported_backend_does_not_run(tmp_path, monkeypatch, platform, backend, supported):
    async def unexpected(*args, **kwargs):
        pytest.fail("unsupported sandbox must not start a process")

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected)
    status = await check_sandbox(ExecToolConfig(sandbox=backend), tmp_path)
    assert status["state"] == "unsupported"
    assert status["supported_backend"] == supported


@pytest.mark.skipif(os.name != "posix", reason="Unix native sandbox")
@pytest.mark.parametrize("env_refs", [False, True])
async def test_native_probe_checks_isolation_without_touching_workspace(tmp_path, monkeypatch, env_refs):
    backend = "seatbelt" if sys.platform == "darwin" else "bwrap"
    config = ExecToolConfig(sandbox=backend)
    status = sandbox_settings_status(config, tmp_path)
    if status["state"] == "unavailable":
        pytest.skip("native sandbox launcher is not installed")
    workspace = tmp_path
    if env_refs:
        monkeypatch.setenv("SANDBOX_TEST_LAUNCHER", status["launcher"])
        monkeypatch.setenv("SANDBOX_TEST_WORKSPACE", str(tmp_path))
        config.sandbox_launcher = "${SANDBOX_TEST_LAUNCHER}"
        workspace = Path("${SANDBOX_TEST_WORKSPACE}")
        status = sandbox_settings_status(config, workspace)
        assert status == sandbox_settings_status(resolve_config_env_vars(config), tmp_path)
    original = tmp_path / "keep.txt"
    original.write_text("user data")
    result = await check_sandbox(config, workspace)
    if backend == "bwrap":
        # An installed launcher is not proof that the host permits namespaces.
        # Establish this independently of nanobot's wrapper and probe. In that
        # environment, detection must report failure and execution stay closed.
        baseline = subprocess.run(
            [status["launcher"], "--ro-bind", "/", "/", "--", "/bin/true"],
            capture_output=True, text=True, timeout=5,
        )
        if baseline.returncode:
            assert "namespace" in baseline.stderr.lower(), baseline.stderr
            assert any(word in baseline.stderr.lower() for word in ("permission denied", "not permitted")), baseline.stderr
            assert result["state"] == "unavailable"
            assert result["reason"] == "probe_failed"
            tool = ExecTool(working_dir=str(tmp_path), sandbox=backend)
            await tool.execute(command="printf unconfined > command-ran")
            assert not (tmp_path / "command-ran").exists()
            assert original.read_text() == "user data"
            return
    assert result["state"] == "passed", result
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt"]
    assert original.read_text() == "user data"
    if env_refs:
        assert config.sandbox_launcher == "${SANDBOX_TEST_LAUNCHER}"
        monkeypatch.setenv("SANDBOX_TEST_WORKSPACE", str(tmp_path / "other"))
        assert sandbox_settings_status(config, workspace)["revision"] != result["revision"]
    # The same resolver and backend must work for actual command execution.
    tool = ExecTool(working_dir=str(tmp_path), sandbox=backend, sandbox_launcher=result["launcher"])
    assert "actual-command" in await tool.execute(command="printf actual-command")
    clock = await tool.execute(command="date +%s")
    assert clock.splitlines()[0].isdigit()
    assert "Exit code: 0" in clock
    failed_command = await tool.execute(command="printf 'sandbox launcher not found: bwrap'; exit 1")
    assert "Exit code: 1" in failed_command
    assert (failed_command.error_code if isinstance(failed_command, ToolResult) else None) is None


@pytest.mark.skipif(os.name != "posix", reason="Unix launch boundary")
@pytest.mark.parametrize("failure_target", ["launcher", "cwd"])
async def test_only_an_os_error_for_the_launcher_is_classified_as_a_sandbox_failure(tmp_path, monkeypatch, failure_target):
    backend = "seatbelt" if sys.platform == "darwin" else "bwrap"
    launcher = "/usr/bin/sandbox-exec" if backend == "seatbelt" else "/bin/sh"

    async def start(*, command, cwd, **kwargs):
        raise PermissionError(13, "launch rejected", command[0] if failure_target == "launcher" else cwd)

    manager = ExecSessionManager()
    monkeypatch.setattr(manager, "start", start)
    tool = ExecTool(working_dir=str(tmp_path), sandbox=backend, sandbox_launcher=launcher, session_manager=manager)
    result = await tool.execute(command="printf not-run")
    assert isinstance(result, ToolResult) and result.is_error
    assert result.error_code == ("sandbox_start_failed" if failure_target == "launcher" else None)


async def test_missing_environment_launcher_does_not_fall_back_or_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SANDBOX_TEST_MISSING_LAUNCHER", raising=False)

    async def unexpected(*args, **kwargs):
        pytest.fail("unresolved launcher must not start a process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected)
    config = ExecToolConfig(sandbox="bwrap", sandbox_launcher="${SANDBOX_TEST_MISSING_LAUNCHER}")
    status = await check_sandbox(config, tmp_path)
    assert status["state"] == "unavailable"
    assert status["reason"] == "path_unavailable"
    assert status["launcher"] is None


def test_probe_revision_changes_when_saved_policy_changes(tmp_path):
    config = ExecToolConfig(sandbox="bwrap")
    before = sandbox_settings_status(config, tmp_path)["revision"]
    config.sandbox_rw_binds = ["/opt/agent-cache"]
    assert sandbox_settings_status(config, tmp_path)["revision"] != before
    assert sandbox_settings_status(ExecToolConfig(sandbox="bwrap"), tmp_path / "other")["revision"] != before


@pytest.mark.skipif(os.name != "posix", reason="Unix process-group cleanup")
@pytest.mark.parametrize("finish", ["timeout", "cancel"])
async def test_probe_reaps_its_process_on_timeout_or_request_cancellation(tmp_path, monkeypatch, finish):
    started, exited = asyncio.Event(), asyncio.Event()
    trusted_launcher = tmp_path / "bwrap"
    trusted_launcher.touch(mode=0o700)
    monkeypatch.setattr(os, "defpath", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")

    class Process:
        pid = 12345
        returncode = None

        async def wait(self):
            await exited.wait()
            return self.returncode

    process = Process()

    async def spawn(*args, **kwargs):
        assert kwargs["start_new_session"]
        assert args[0] == str(trusted_launcher)
        assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == asyncio.subprocess.DEVNULL
        assert kwargs["env"] == {"PATH": str(tmp_path), "HOME": kwargs["cwd"]}
        started.set()
        return process

    def kill(pid, sig):
        assert (pid, sig) == (process.pid, signal.SIGKILL)
        process.returncode = -9
        exited.set()

    monkeypatch.setattr("nanobot.agent.tools.sandbox_check._PROBE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(os, "killpg", kill)
    task = asyncio.create_task(check_sandbox(ExecToolConfig(sandbox="bwrap"), tmp_path))
    await asyncio.wait_for(started.wait(), 1)
    if finish == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task)["reason"] == "probe_timeout"
    assert exited.is_set()
    assert process.returncode == -9
