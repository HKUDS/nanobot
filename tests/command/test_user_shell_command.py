from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.events import INBOUND_META_USER_SHELL, InboundMessage
from nanobot.command.router import CommandContext
from nanobot.command.user_shell import cmd_user_shell
from nanobot.session.manager import Session, SessionPolicy


def _context(loop: MagicMock, *, trusted: bool, command: str = "pwd") -> CommandContext:
    metadata = {
        "webui": True,
        **({INBOUND_META_USER_SHELL: True} if trusted else {}),
    }
    msg = InboundMessage(
        channel="websocket",
        sender_id="local-user",
        chat_id="chat",
        content=f"!{command}",
        metadata=metadata,
    )
    return CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw=msg.content,
        args=command,
        loop=loop,
    )


@pytest.mark.asyncio
async def test_user_shell_rejects_untrusted_transport_metadata() -> None:
    loop = MagicMock()

    response = await cmd_user_shell(_context(loop, trusted=False))

    assert "trusted local client" in response.content
    loop.tools.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("context_session", [True, False])
async def test_user_shell_uses_exec_tool_with_workspace_scope(
    tmp_path: Path, log_content: bool, context_session: bool,
) -> None:
    async def execute(**kwargs):
        request = current_request_context()
        assert request is not None
        assert request.log_content is log_content
        assert request.workspace == tmp_path
        return f"{tmp_path}\n\nExit code: 0"

    tool = MagicMock(spec=ExecTool)
    tool.execute_to_completion = AsyncMock(side_effect=execute)
    session = Session(key="websocket:chat", policy=SessionPolicy(log_content=log_content))
    scope = SimpleNamespace(project_path=tmp_path)
    loop = MagicMock()
    loop.tools.get.return_value = tool
    loop.sessions.state.get = AsyncMock(return_value=session)
    loop.workspace_scopes.for_turn.return_value = scope
    ctx = _context(loop, trusted=True)
    if context_session:
        ctx.session = session

    response = await cmd_user_shell(ctx)

    tool.execute_to_completion.assert_awaited_once_with(command="pwd", working_dir=str(tmp_path))
    assert response.content.endswith("Exit code: 0")
    assert response.metadata["render_as"] == "text"
    assert current_request_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("command, disabled", [("", False), ("pwd", True)])
async def test_user_shell_reports_missing_command_or_disabled_execution(command, disabled) -> None:
    loop = MagicMock()
    loop.tools.get.return_value = None
    response = await cmd_user_shell(_context(loop, trusted=True, command=command))
    assert ("disabled" if disabled else "Type a command") in response.content
    loop.sessions.state.get.assert_not_called()


@pytest.mark.asyncio
async def test_user_command_keeps_waiting_for_full_result_while_model_observation_is_bounded(tmp_path):
    import shlex
    import sys

    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.bus.queue import MessageBus
    from nanobot.security.workspace_access import default_workspace_scope

    manager = ExecSessionManager()
    tool = ExecTool(working_dir=str(tmp_path), session_manager=manager)
    snippet = 'import time; print("first", flush=True); time.sleep(.15); print("last")'
    command = f"{shlex.quote(sys.executable)} -I -c {shlex.quote(snippet)}"
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "unused-model"
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    loop.tools.register(tool)
    ctx = _context(loop, trusted=True, command=command)
    scope = default_workspace_scope(tmp_path, False, source_channel="websocket")
    ctx.session = Session(key=ctx.key, metadata={"workspace_scope": scope.metadata()})
    try:
        bounded = await tool.execute(command=command, yield_time_ms=0)
        assert "Process running" in bounded
        response = await cmd_user_shell(ctx)
        assert "first" in response.content and "last" in response.content
        assert "Exit code: 0" in response.content and response.metadata["render_as"] == "text"
        assert current_request_context() is None
    finally:
        await manager.close_all()
        await loop.aclose()


@pytest.mark.asyncio
async def test_shell_cancellation_unwinds_turn_scopes_and_request_policy(tmp_path):
    import asyncio
    from contextlib import contextmanager

    entered, release = asyncio.Event(), asyncio.Event()
    changes = []

    @contextmanager
    def turn_scope():
        changes.append("enter")
        try:
            yield
        finally:
            changes.append("exit")

    async def execute(**kwargs):
        assert current_request_context().session_key == "websocket:chat"
        entered.set()
        await release.wait()
        return "not reached"

    tool = MagicMock(spec=ExecTool)
    tool.execute_to_completion = AsyncMock(side_effect=execute)
    loop = MagicMock()
    loop.tools.get.return_value = tool
    loop.workspace_scopes.for_turn.return_value = SimpleNamespace(project_path=tmp_path)
    ctx = _context(loop, trusted=True)
    ctx.session = Session(key=ctx.key)
    ctx.turn_scopes = (turn_scope(),)
    task = asyncio.create_task(cmd_user_shell(ctx))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert changes == ["enter", "exit"]
    assert current_request_context() is None
