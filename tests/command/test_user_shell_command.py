from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.bus.events import INBOUND_META_USER_SHELL, InboundMessage, OutboundMessage
from nanobot.command.builtin import cmd_user_shell
from nanobot.command.router import CommandContext
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
    loop.execute_user_shell_command = AsyncMock()

    response = await cmd_user_shell(_context(loop, trusted=False))

    assert "trusted local client" in response.content
    loop.execute_user_shell_command.assert_not_awaited()


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

    tool = MagicMock()
    tool.execute = AsyncMock(side_effect=execute)
    session = Session(key="websocket:chat", policy=SessionPolicy(log_content=log_content))
    scope = SimpleNamespace(project_path=tmp_path)
    loop = MagicMock()
    loop.tools.get.return_value = tool
    loop.sessions.get_or_create.return_value = session
    loop.workspace_scopes.for_turn.return_value = scope
    ctx = _context(loop, trusted=True)
    if context_session:
        ctx.session = session

    response = await AgentLoop.execute_user_shell_command(loop, ctx)

    tool.execute.assert_awaited_once_with(command="pwd", working_dir=str(tmp_path))
    assert response.content.endswith("Exit code: 0")
    assert response.metadata["render_as"] == "text"
    assert current_request_context() is None


@pytest.mark.asyncio
async def test_user_shell_delegates_trusted_request_to_agent_loop() -> None:
    loop = MagicMock()
    expected = OutboundMessage(channel="websocket", chat_id="chat", content="ok")
    loop.execute_user_shell_command = AsyncMock(return_value=expected)
    ctx = _context(loop, trusted=True, command="printf ok")

    response = await cmd_user_shell(ctx)

    assert response is expected
    loop.execute_user_shell_command.assert_awaited_once_with(ctx)
