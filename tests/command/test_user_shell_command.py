from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import INBOUND_META_USER_SHELL, InboundMessage, OutboundMessage
from nanobot.command.builtin import cmd_user_shell
from nanobot.command.router import CommandContext
from nanobot.session.async_manager import AsyncSessionManager


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
async def test_user_shell_uses_exec_tool_with_workspace_scope(tmp_path: Path) -> None:
    tool = MagicMock()
    tool.execute = AsyncMock(return_value=f"{tmp_path}\n\nExit code: 0")
    session = SimpleNamespace(metadata={})
    scope = SimpleNamespace(project_path=tmp_path)
    loop = MagicMock()
    loop.tools.get.return_value = tool
    loop.sessions.get_or_create.return_value = session
    loop.session_io = AsyncSessionManager(loop.sessions)
    loop.workspace_scopes.for_turn.return_value = scope
    ctx = _context(loop, trusted=True)

    response = await AgentLoop.execute_user_shell_command(loop, ctx)

    tool.execute.assert_awaited_once_with(command="pwd", working_dir=str(tmp_path))
    assert response.content.endswith("Exit code: 0")
    assert response.metadata["render_as"] == "text"


@pytest.mark.asyncio
async def test_user_shell_delegates_trusted_request_to_agent_loop() -> None:
    loop = MagicMock()
    expected = OutboundMessage(channel="websocket", chat_id="chat", content="ok")
    loop.execute_user_shell_command = AsyncMock(return_value=expected)
    ctx = _context(loop, trusted=True, command="printf ok")

    response = await cmd_user_shell(ctx)

    assert response is expected
    loop.execute_user_shell_command.assert_awaited_once_with(ctx)
