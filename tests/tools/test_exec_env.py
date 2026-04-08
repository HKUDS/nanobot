"""Tests for exec tool environment isolation."""

import sys

import pytest

from nanobot.agent.tools.shell import ExecTool

_UNIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Unix shell commands")


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_does_not_leak_parent_env(monkeypatch):
    """Env vars from the parent process must not be visible to commands."""
    monkeypatch.setenv("NANOBOT_SECRET_TOKEN", "super-secret-value")
    tool = ExecTool()
    command = "printenv NANOBOT_SECRET_TOKEN" if sys.platform != "win32" else "echo $env:NANOBOT_SECRET_TOKEN"
    result = await tool.execute(command=command)
    assert "super-secret-value" not in result


@pytest.mark.asyncio
async def test_exec_has_working_path():
    """Basic commands should be available via the login shell's PATH."""
    tool = ExecTool()
    result = await tool.execute(command="echo hello")
    assert "hello" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append():
    """The pathAppend config should be available in the command's PATH."""
    tool = ExecTool(path_append="/opt/custom/bin")
    command = "echo $PATH" if sys.platform != "win32" else "echo $env:PATH"
    result = await tool.execute(command=command)
    assert "/opt/custom/bin" in result


@_UNIX_ONLY
@pytest.mark.asyncio
async def test_exec_path_append_preserves_system_path():
    """pathAppend must not clobber standard system paths."""
    tool = ExecTool(path_append="/opt/custom/bin")
    result = await tool.execute(command="ls /")
    assert "Exit code: 0" in result


@pytest.mark.asyncio
async def test_exec_can_run_docker_on_windows():
    """Windows exec should be able to reach Docker Desktop directly."""
    if sys.platform != "win32":
        pytest.skip("Windows-only behavior")

    tool = ExecTool(path_append="/mnt/d/Docker/resources/bin")
    result = await tool.execute(command='docker version --format "{{.Server.Version}}"')
    assert "Exit code: 0" in result
