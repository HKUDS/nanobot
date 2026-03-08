"""Tests for Docker sandbox execution in ExecTool."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from nanobot.config.schema import SandboxConfig
from nanobot.agent.tools.shell import ExecTool


# --- Unit tests for _docker_available ---

def test_docker_available_when_present():
    with patch("shutil.which", return_value="/usr/bin/docker"):
        assert ExecTool._docker_available() is True


def test_docker_not_available():
    with patch("shutil.which", return_value=None):
        assert ExecTool._docker_available() is False


# --- Unit tests for _build_docker_command ---

def test_build_docker_command_defaults():
    sandbox = SandboxConfig(enabled=True)
    tool = ExecTool(working_dir="/home/user/workspace", sandbox=sandbox)
    cmd = tool._build_docker_command("echo hello", "/home/user/workspace")

    assert cmd[0:3] == ["docker", "run", "--rm"]
    assert "--memory=512m" in cmd
    assert "--cpus=1.0" in cmd
    assert "--network=none" in cmd
    assert "-v" in cmd
    assert "/home/user/workspace:/workspace" in cmd
    assert cmd[-3:] == ["sh", "-c", "echo hello"]


def test_build_docker_command_custom_image():
    sandbox = SandboxConfig(enabled=True, image="node:20-slim")
    tool = ExecTool(working_dir="/workspace", sandbox=sandbox)
    cmd = tool._build_docker_command("node -e '1+1'", "/workspace")

    assert "node:20-slim" in cmd


def test_build_docker_command_no_workspace_mount():
    sandbox = SandboxConfig(enabled=True, mount_workspace=False)
    tool = ExecTool(working_dir="/workspace", sandbox=sandbox)
    cmd = tool._build_docker_command("ls", "/workspace")

    assert "-v" not in cmd
    assert "-w" in cmd
    assert "/workspace" in cmd


def test_build_docker_command_no_working_dir():
    """mount_workspace=True but no working_dir set — should skip volume mount."""
    sandbox = SandboxConfig(enabled=True, mount_workspace=True)
    tool = ExecTool(sandbox=sandbox)  # no working_dir
    cmd = tool._build_docker_command("ls", "/tmp")

    assert "-v" not in cmd


def test_build_docker_command_custom_limits():
    sandbox = SandboxConfig(
        enabled=True,
        memory_limit="1g",
        cpu_limit=2.0,
        network="bridge",
    )
    tool = ExecTool(working_dir="/ws", sandbox=sandbox)
    cmd = tool._build_docker_command("python script.py", "/ws")

    assert "--memory=1g" in cmd
    assert "--cpus=2.0" in cmd
    assert "--network=bridge" in cmd


# --- Unit tests for _format_output ---

def test_format_output_success():
    result = ExecTool._format_output(b"hello world\n", b"", 0)
    assert result == "hello world\n"


def test_format_output_with_stderr():
    result = ExecTool._format_output(b"out\n", b"warn: something\n", 0)
    assert "out" in result
    assert "STDERR:" in result
    assert "warn: something" in result


def test_format_output_nonzero_exit():
    result = ExecTool._format_output(b"", b"error\n", 1)
    assert "Exit code: 1" in result


def test_format_output_empty():
    result = ExecTool._format_output(b"", b"", 0)
    assert result == "(no output)"


def test_format_output_truncation():
    long_output = b"x" * 20000
    result = ExecTool._format_output(long_output, b"", 0)
    assert "truncated" in result
    assert len(result) < 20000


# --- Unit tests for execute routing ---

@pytest.mark.asyncio
async def test_execute_routes_to_direct_when_sandbox_disabled():
    sandbox = SandboxConfig(enabled=False)
    tool = ExecTool(working_dir="/tmp", sandbox=sandbox)

    with patch.object(tool, "_run_direct", new_callable=AsyncMock, return_value="direct") as mock_direct, \
         patch.object(tool, "_run_sandboxed", new_callable=AsyncMock) as mock_sandboxed:
        result = await tool.execute(command="echo hi")
        mock_direct.assert_called_once()
        mock_sandboxed.assert_not_called()
        assert result == "direct"


@pytest.mark.asyncio
async def test_execute_routes_to_sandboxed_when_enabled_and_docker_available():
    sandbox = SandboxConfig(enabled=True)
    tool = ExecTool(working_dir="/tmp", sandbox=sandbox)

    with patch.object(tool, "_run_sandboxed", new_callable=AsyncMock, return_value="sandboxed") as mock_sandboxed, \
         patch.object(ExecTool, "_docker_available", return_value=True):
        result = await tool.execute(command="echo hi")
        mock_sandboxed.assert_called_once()
        assert result == "sandboxed"


@pytest.mark.asyncio
async def test_execute_falls_back_to_direct_when_docker_unavailable():
    sandbox = SandboxConfig(enabled=True)
    tool = ExecTool(working_dir="/tmp", sandbox=sandbox)

    with patch.object(tool, "_run_direct", new_callable=AsyncMock, return_value="direct") as mock_direct, \
         patch.object(ExecTool, "_docker_available", return_value=False):
        result = await tool.execute(command="echo hi")
        mock_direct.assert_called_once()
        assert result == "direct"


# --- Guard still applies before sandbox ---

@pytest.mark.asyncio
async def test_guard_blocks_before_sandbox():
    sandbox = SandboxConfig(enabled=True)
    tool = ExecTool(working_dir="/tmp", sandbox=sandbox)

    with patch.object(ExecTool, "_docker_available", return_value=True):
        result = await tool.execute(command="rm -rf /")
        assert "blocked by safety guard" in result


# --- SandboxConfig defaults ---

def test_sandbox_config_defaults():
    cfg = SandboxConfig()
    assert cfg.enabled is False
    assert cfg.image == "python:3.12-slim"
    assert cfg.memory_limit == "512m"
    assert cfg.cpu_limit == 1.0
    assert cfg.network == "none"
    assert cfg.timeout == 60
    assert cfg.mount_workspace is True


def test_sandbox_config_in_exec_tool_config():
    from nanobot.config.schema import ExecToolConfig
    cfg = ExecToolConfig()
    assert cfg.sandbox.enabled is False
    assert cfg.sandbox.image == "python:3.12-slim"


def test_sandbox_config_override():
    from nanobot.config.schema import ExecToolConfig
    cfg = ExecToolConfig(sandbox=SandboxConfig(enabled=True, image="ubuntu:24.04"))
    assert cfg.sandbox.enabled is True
    assert cfg.sandbox.image == "ubuntu:24.04"
