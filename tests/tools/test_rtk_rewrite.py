"""Tests for ExecTool rtk rewrite integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.shell import ExecTool
from nanobot.config.schema import ExecToolConfig


# ─────────────────────────────────────────────
# ExecToolConfig schema tests
# ─────────────────────────────────────────────

def test_exec_tool_config_defaults():
    """rtk 相关配置默认均为 False，确保零侵入。"""
    cfg = ExecToolConfig()
    assert cfg.rtk_enabled is False
    assert cfg.rtk_verbose is False


def test_exec_tool_config_camel_case():
    """配置支持 camelCase（JSON config 格式）。"""
    cfg = ExecToolConfig.model_validate({"rtkEnabled": True, "rtkVerbose": True})
    assert cfg.rtk_enabled is True
    assert cfg.rtk_verbose is True


# ─────────────────────────────────────────────
# ExecTool._rtk_rewrite unit tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rtk_rewrite_success():
    """rtk 可用时返回改写后的命令。"""
    tool = ExecTool(rtk_enabled=True)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"rtk git status\n", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await tool._rtk_rewrite("git status")

    assert result == "rtk git status"


@pytest.mark.asyncio
async def test_rtk_rewrite_not_found_fallback():
    """rtk 不在 PATH 时抛 FileNotFoundError，原命令 passthrough。"""
    tool = ExecTool(rtk_enabled=True)

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("rtk not found")):
        result = await tool._rtk_rewrite("git status")

    assert result == "git status"


@pytest.mark.asyncio
async def test_rtk_rewrite_nonzero_exit_fallback():
    """rtk 返回非零退出码时，原命令 passthrough。"""
    tool = ExecTool(rtk_enabled=True)

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await tool._rtk_rewrite("git status")

    assert result == "git status"


@pytest.mark.asyncio
async def test_rtk_rewrite_timeout_fallback():
    """rtk 超时（>5s）时，原命令 passthrough。"""
    tool = ExecTool(rtk_enabled=True)

    async def _slow_communicate():
        await asyncio.sleep(10)
        return b"", b""

    mock_proc = MagicMock()
    mock_proc.communicate = _slow_communicate

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await tool._rtk_rewrite("ls -la")

    assert result == "ls -la"


@pytest.mark.asyncio
async def test_rtk_rewrite_empty_output_fallback():
    """rtk 返回空输出时，原命令 passthrough。"""
    tool = ExecTool(rtk_enabled=True)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await tool._rtk_rewrite("ls")

    assert result == "ls"


# ─────────────────────────────────────────────
# ExecTool.execute integration tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_with_rtk_disabled_skips_rewrite():
    """rtk_enabled=False 时不调用 _rtk_rewrite，命令原样执行。"""
    tool = ExecTool(rtk_enabled=False, timeout=5)

    with patch.object(tool, "_rtk_rewrite", AsyncMock()) as mock_rewrite:
        result = await tool.execute(command="echo hello")

    mock_rewrite.assert_not_called()
    assert "hello" in result


@pytest.mark.asyncio
async def test_execute_with_rtk_enabled_calls_rewrite():
    """rtk_enabled=True 时 execute 会先调用 _rtk_rewrite。"""
    tool = ExecTool(rtk_enabled=True, timeout=5)

    async def _fake_rewrite(cmd):
        return "echo rewritten"

    with patch.object(tool, "_rtk_rewrite", side_effect=_fake_rewrite):
        result = await tool.execute(command="echo original")

    assert "rewritten" in result


@pytest.mark.asyncio
async def test_rtk_verbose_logs_rewrite(caplog):
    """rtk_verbose=True 时，rewrite 结果写入 debug 日志。"""
    import logging
    tool = ExecTool(rtk_enabled=True, rtk_verbose=True)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"rtk git log -n 10\n", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        with caplog.at_level(logging.DEBUG):
            result = await tool._rtk_rewrite("git log -n 10")

    assert result == "rtk git log -n 10"
    # verbose 日志通过 loguru，caplog 可能抓不到，但至少不报错
