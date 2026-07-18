from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.tools.command_rewriters import (
    RTKCommandRewriter,
    RTKCommandRewriterConfig,
    filter_rtk_hook_warnings,
)
from nanobot.agent.tools.shell import ExecTool, ExecToolConfig


def _mock_process(stdout: bytes = b"ok\n", stderr: bytes = b"", returncode: int = 0):
    process = AsyncMock()
    process.communicate.return_value = (stdout, stderr)
    process.returncode = returncode
    return process


@pytest.mark.asyncio
async def test_exec_rtk_rewrites_command_and_sets_workspace_tee_dir(tmp_path):
    captured: dict[str, object] = {}

    async def fake_run_rewrite(self, executable, command, cwd, env):
        captured["rewrite_executable"] = executable
        captured["rewrite_command"] = command
        captured["rewrite_cwd"] = cwd
        captured["rewrite_env"] = dict(env)
        return 3, b"rtk pytest tests -q\n", b""

    async def capture_spawn(command, cwd, env, shell_program=None, login=False, *, stdin=None):
        captured["spawn_command"] = command
        captured["spawn_cwd"] = cwd
        captured["spawn_env"] = dict(env)
        return _mock_process()

    with (
        patch.object(RTKCommandRewriter, "_resolve_binary", return_value="rtk"),
        patch.object(RTKCommandRewriter, "_run_rewrite", fake_run_rewrite),
        patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
    ):
        tool = ExecTool(
            working_dir=str(tmp_path),
            rtk=RTKCommandRewriterConfig(enabled=True),
        )
        result = await tool.execute(command="pytest tests -q")

    tee_dir = tmp_path / ".nanobot" / "rtk-tee"
    assert "ok" in result
    assert captured["rewrite_executable"] == "rtk"
    assert captured["rewrite_command"] == "pytest tests -q"
    assert captured["spawn_command"] == "rtk pytest tests -q"
    assert captured["spawn_env"]["RTK_TEE_DIR"] == str(tee_dir)
    assert tee_dir.is_dir()


@pytest.mark.asyncio
async def test_exec_rtk_fail_opens_when_rewrite_is_unsupported(tmp_path):
    captured: dict[str, object] = {}

    async def fake_run_rewrite(self, executable, command, cwd, env):
        return 1, b"", b"unsupported"

    async def capture_spawn(command, cwd, env, shell_program=None, login=False, *, stdin=None):
        captured["spawn_command"] = command
        return _mock_process()

    with (
        patch.object(RTKCommandRewriter, "_resolve_binary", return_value="rtk"),
        patch.object(RTKCommandRewriter, "_run_rewrite", fake_run_rewrite),
        patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
    ):
        tool = ExecTool(
            working_dir=str(tmp_path),
            rtk=RTKCommandRewriterConfig(enabled=True),
        )
        result = await tool.execute(command="echo hello")

    assert "ok" in result
    assert captured["spawn_command"] == "echo hello"


@pytest.mark.asyncio
async def test_exec_rtk_does_not_wrap_same_command_again(tmp_path):
    captured: dict[str, object] = {}

    async def fake_run_rewrite(self, executable, command, cwd, env):
        return 3, b"rtk pytest tests -q\n", b""

    async def capture_spawn(command, cwd, env, shell_program=None, login=False, *, stdin=None):
        captured["spawn_command"] = command
        return _mock_process()

    with (
        patch.object(RTKCommandRewriter, "_resolve_binary", return_value="rtk"),
        patch.object(RTKCommandRewriter, "_run_rewrite", fake_run_rewrite),
        patch.object(ExecTool, "_spawn", side_effect=capture_spawn),
    ):
        tool = ExecTool(
            working_dir=str(tmp_path),
            rtk=RTKCommandRewriterConfig(enabled=True),
        )
        result = await tool.execute(command="rtk pytest tests -q")

    assert "ok" in result
    assert captured["spawn_command"] == "rtk pytest tests -q"


@pytest.mark.asyncio
async def test_exec_rtk_rewritten_command_must_pass_guard(tmp_path):
    async def fake_run_rewrite(self, executable, command, cwd, env):
        return 3, b"rm -rf build\n", b""

    with (
        patch.object(RTKCommandRewriter, "_resolve_binary", return_value="rtk"),
        patch.object(RTKCommandRewriter, "_run_rewrite", fake_run_rewrite),
        patch.object(ExecTool, "_spawn", new_callable=AsyncMock) as mock_spawn,
    ):
        tool = ExecTool(
            working_dir=str(tmp_path),
            rtk=RTKCommandRewriterConfig(enabled=True),
        )
        result = await tool.execute(command="pytest tests -q")

    assert "deny pattern filter" in result
    mock_spawn.assert_not_called()


def test_exec_config_accepts_rtk_camel_case_aliases():
    config = ExecToolConfig(rtk={"enabled": True, "rewriteTimeoutMs": 1234})

    assert config.rtk.enabled is True
    assert config.rtk.rewrite_timeout_ms == 1234


def test_rtk_hook_warning_filter_removes_only_warning_line():
    text = "[rtk] /!\\ No hook installed - run `rtk init -g`\nreal output\n"

    assert filter_rtk_hook_warnings(text) == "real output\n"
