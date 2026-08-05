from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.context import (
    RequestContext,
    ToolContext,
    bind_request_context,
    reset_request_context,
)
from nanobot.agent.tools.exec_session import WriteStdinTool
from nanobot.agent.tools.shell import ExecTool, ExecToolConfig
from nanobot.agent.tools.terminal import TerminalTool
from nanobot.config.schema import ToolsConfig
from nanobot.security.workspace_access import (
    bind_workspace_scope,
    build_workspace_scope,
    reset_workspace_scope,
)
from nanobot.terminal.runtime import (
    TRUSTED_TERMINAL_REQUEST_METADATA_KEY,
    TerminalExecPoll,
    TerminalInfo,
    TerminalRead,
)


def _trusted_request() -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        metadata={TRUSTED_TERMINAL_REQUEST_METADATA_KEY: True},
    )


def test_terminal_tool_respects_exec_command_policy(tmp_path: Path) -> None:
    manager = MagicMock()
    default = ToolContext(
        config=ToolsConfig(exec=ExecToolConfig()),
        workspace=str(tmp_path),
        terminal_session_manager=manager,
    )
    sandboxed = ToolContext(
        config=ToolsConfig(exec=ExecToolConfig(sandbox="bwrap")),
        workspace=str(tmp_path),
        terminal_session_manager=manager,
    )
    filtered = ToolContext(
        config=ToolsConfig(exec=ExecToolConfig(deny_patterns=["dangerous"])),
        workspace=str(tmp_path),
        terminal_session_manager=manager,
    )

    assert TerminalTool.enabled(default) is True
    assert TerminalTool.enabled(sandboxed) is False
    assert TerminalTool.enabled(filtered) is False


@pytest.mark.asyncio
async def test_terminal_tool_opens_the_current_full_access_webui_project(
    tmp_path: Path,
) -> None:
    manager = MagicMock()
    manager.open = AsyncMock(
        return_value=TerminalInfo(
            terminal_id="term-1",
            project_path=str(tmp_path),
            rows=30,
            cols=100,
            running=True,
            exit_code=None,
            created_at=1.0,
        )
    )
    tool = TerminalTool(manager)
    request_token = bind_request_context(
        _trusted_request()
    )
    scope_token = bind_workspace_scope(
        build_workspace_scope(tmp_path, "full", source_channel="websocket")
    )
    try:
        result = await tool.execute("open")
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    assert json.loads(result)["terminal_id"] == "term-1"
    manager.open.assert_awaited_once_with(tmp_path.resolve(), rows=30, cols=100)


@pytest.mark.asyncio
async def test_terminal_tool_rejects_restricted_or_non_webui_contexts(
    tmp_path: Path,
) -> None:
    manager = MagicMock()
    manager.open = AsyncMock()
    tool = TerminalTool(manager)

    request_token = bind_request_context(
        _trusted_request()
    )
    scope_token = bind_workspace_scope(
        build_workspace_scope(tmp_path, "restricted", source_channel="websocket")
    )
    try:
        restricted = await tool.execute("open")
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    request_token = bind_request_context(RequestContext(channel="telegram", chat_id="chat-1"))
    scope_token = bind_workspace_scope(build_workspace_scope(tmp_path, "full"))
    try:
        wrong_channel = await tool.execute("open")
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    assert isinstance(restricted, ToolResult) and restricted.is_error
    assert "Full access" in restricted
    assert isinstance(wrong_channel, ToolResult) and wrong_channel.is_error
    assert "WebUI" in wrong_channel
    manager.open.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_tool_rejects_untrusted_websocket_request(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.open = AsyncMock()
    tool = TerminalTool(manager)
    request_token = bind_request_context(
        RequestContext(channel="websocket", chat_id="chat-1")
    )
    scope_token = bind_workspace_scope(
        build_workspace_scope(tmp_path, "full", source_channel="websocket")
    )
    try:
        result = await tool.execute("open")
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    assert isinstance(result, ToolResult) and result.is_error
    assert "trusted local" in result
    manager.open.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_tool_write_returns_only_new_output(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.read = AsyncMock(
        side_effect=[
            TerminalRead(data="", next_seq=7, running=True, exit_code=None),
            TerminalRead(data="ok\r\n", next_seq=8, running=True, exit_code=None),
        ]
    )
    manager.write = AsyncMock()
    tool = TerminalTool(manager)
    request_token = bind_request_context(
        _trusted_request()
    )
    scope_token = bind_workspace_scope(
        build_workspace_scope(tmp_path, "full", source_channel="websocket")
    )
    try:
        result = await tool.execute(
            "write",
            terminal_id="term-1",
            input="git status",
        )
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    manager.write.assert_awaited_once_with(
        "term-1",
        "git status\r",
        project_path=tmp_path.resolve(),
    )
    assert json.loads(result)["data"] == "ok\r\n"


@pytest.mark.asyncio
async def test_exec_and_write_stdin_use_the_trusted_shared_terminal(
    tmp_path: Path,
) -> None:
    manager = MagicMock()
    manager.supports_exec_bridge = True
    manager.shell_family = "powershell"
    manager.is_exec_session_id.side_effect = lambda value: value.startswith("termexec-")
    manager.start_exec = AsyncMock(return_value=(
        "termexec-1",
        TerminalExecPoll(
            output="ready\r\n",
            done=False,
            exit_code=None,
        ),
    ))
    manager.write_exec = AsyncMock(return_value=TerminalExecPoll(
        output="done\r\n",
        done=True,
        exit_code=0,
    ))
    exec_tool = ExecTool(
        working_dir=str(tmp_path),
        terminal_session_manager=manager,
        terminal_bridge_enabled=True,
    )
    stdin_tool = WriteStdinTool(
        terminal_manager=manager,
        terminal_bridge_enabled=True,
    )
    request_token = bind_request_context(_trusted_request())
    scope_token = bind_workspace_scope(
        build_workspace_scope(tmp_path, "full", source_channel="websocket")
    )
    try:
        initial = await exec_tool.execute(
            command="Write-Output ready; Start-Sleep 10",
            yield_time_ms=0,
        )
        final = await stdin_tool.execute(
            session_id="termexec-1",
            chars="input\r",
            yield_time_ms=100,
        )
    finally:
        reset_workspace_scope(scope_token)
        reset_request_context(request_token)

    assert "Process running. session_id: termexec-1" in initial
    assert "done" in final
    manager.start_exec.assert_awaited_once()
    manager.write_exec.assert_awaited_once_with(
        "termexec-1",
        chars="input\r",
        close_stdin=False,
        terminate=False,
        yield_time_ms=100,
        max_output_chars=10_000,
        owner_session_key="websocket:chat-1",
    )
