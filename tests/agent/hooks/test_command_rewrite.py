"""Tests for CommandRewriteHook — cross-cutting tool argument rewrite hook.

Current strategy under test: rtk command compression.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.hooks.rewrite import CommandRewriteHook
from nanobot.providers.base import ToolCallRequest


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _exec_tc(command: str, tid: str = "call_1") -> ToolCallRequest:
    return ToolCallRequest(id=tid, name="exec", arguments={"command": command})


def _ctx(tool_calls: list[ToolCallRequest]) -> AgentHookContext:
    return AgentHookContext(iteration=0, messages=[], tool_calls=tool_calls)


def _mock_proc(stdout: bytes = b"", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


# ─────────────────────────────────────────────
#  Disabled path
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_disabled_skips_rewrite():
    """enabled=False 时完全不调 subprocess。"""
    hook = CommandRewriteHook(enabled=False)
    tc = _exec_tc("git status")
    ctx = _ctx([tc])

    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        await hook.before_execute_tools(ctx)

    spawn.assert_not_called()
    assert tc.arguments["command"] == "git status"


# ─────────────────────────────────────────────
#  Happy path
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_rewrites_exec_command():
    """正常情况命令被改写。"""
    hook = CommandRewriteHook(enabled=True)
    tc = _exec_tc("git status")
    ctx = _ctx([tc])

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=_mock_proc(b"rtk git status\n")),
    ):
        await hook.before_execute_tools(ctx)

    assert tc.arguments["command"] == "rtk git status"


@pytest.mark.asyncio
async def test_hook_handles_multiple_exec_calls():
    """一轮多个 exec tool_call 全部改写。"""
    hook = CommandRewriteHook(enabled=True)
    tc1 = _exec_tc("git status", tid="call_1")
    tc2 = _exec_tc("ls -la", tid="call_2")
    ctx = _ctx([tc1, tc2])

    # 每次调用返回不同结果
    proc1 = _mock_proc(b"rtk git status\n")
    proc2 = _mock_proc(b"rtk ls -la\n")

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[proc1, proc2]),
    ):
        await hook.before_execute_tools(ctx)

    assert tc1.arguments["command"] == "rtk git status"
    assert tc2.arguments["command"] == "rtk ls -la"


# ─────────────────────────────────────────────
#  Filtering
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_ignores_non_exec_tool_calls():
    """非 exec 工具完全不处理。"""
    hook = CommandRewriteHook(enabled=True)
    tc = ToolCallRequest(id="c1", name="read_file", arguments={"path": "/etc/passwd"})
    ctx = _ctx([tc])

    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        await hook.before_execute_tools(ctx)

    spawn.assert_not_called()
    assert tc.arguments == {"path": "/etc/passwd"}


@pytest.mark.asyncio
async def test_hook_ignores_missing_command_arg():
    """exec 但 arguments 无 command 键时静默跳过。"""
    hook = CommandRewriteHook(enabled=True)
    tc = ToolCallRequest(id="c1", name="exec", arguments={"timeout": 10})
    ctx = _ctx([tc])

    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        await hook.before_execute_tools(ctx)

    spawn.assert_not_called()
    assert tc.arguments == {"timeout": 10}


# ─────────────────────────────────────────────
#  Fail-safe paths
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_fail_safe_on_subprocess_error():
    """spawn 失败（rtk 不可用）时原命令透传。"""
    hook = CommandRewriteHook(enabled=True)
    tc = _exec_tc("git status")
    ctx = _ctx([tc])

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("rtk")),
    ):
        await hook.before_execute_tools(ctx)

    assert tc.arguments["command"] == "git status"


@pytest.mark.asyncio
async def test_hook_fail_safe_on_nonzero_returncode():
    """rtk 返回非零退出码时原命令透传。"""
    hook = CommandRewriteHook(enabled=True)
    tc = _exec_tc("git status")
    ctx = _ctx([tc])

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=_mock_proc(b"", returncode=1)),
    ):
        await hook.before_execute_tools(ctx)

    assert tc.arguments["command"] == "git status"


@pytest.mark.asyncio
async def test_hook_timeout_fail_safe():
    """subprocess 超时时原命令透传。"""
    hook = CommandRewriteHook(enabled=True, timeout=0.01)
    tc = _exec_tc("git status")
    ctx = _ctx([tc])

    proc = MagicMock()
    proc.returncode = 0

    async def _hang(*args, **kwargs):
        await asyncio.sleep(10)
        return (b"rtk git status\n", b"")

    proc.communicate = _hang

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        await hook.before_execute_tools(ctx)

    assert tc.arguments["command"] == "git status"


# ─────────────────────────────────────────────
#  Verbose logging
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_verbose_logs_on_change(capsys):
    """verbose=True 时，rewrite 结果通过 loguru logger.debug 记录。"""
    from loguru import logger
    import sys

    sink_id = logger.add(sys.stderr, level="DEBUG", format="{message}")
    try:
        hook = CommandRewriteHook(enabled=True, verbose=True)
        tc = _exec_tc("git status")
        ctx = _ctx([tc])

        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=_mock_proc(b"rtk git status\n")),
        ):
            await hook.before_execute_tools(ctx)
    finally:
        logger.remove(sink_id)

    captured = capsys.readouterr()
    assert "rtk rewrite" in captured.err or "git status" in captured.err
