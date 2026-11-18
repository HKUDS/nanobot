from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext


@pytest.mark.parametrize(("count", "content"), [
    (3, "Stopped 3 task(s)."),
    (0, "No active task to stop."),
])
async def test_cmd_stop_reports_session_cancellation(count, content):
    loop = MagicMock(_cancel_active_tasks=AsyncMock(return_value=count))
    msg = InboundMessage(channel="websocket", sender_id="user", chat_id="chat", content="/stop")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, loop=loop)

    result = await cmd_stop(ctx)

    loop._cancel_active_tasks.assert_awaited_once_with(msg.session_key)
    assert (result.channel, result.chat_id, result.content) == (msg.channel, msg.chat_id, content)
