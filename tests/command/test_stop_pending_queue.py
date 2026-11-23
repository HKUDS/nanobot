from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import CommandResultEvent
from nanobot.command.builtin import cmd_stop
from nanobot.command.results import message_text
from nanobot.command.router import CommandContext


@pytest.mark.parametrize("count", [0, 3])
@pytest.mark.parametrize(("channel", "metadata", "expected"), [
    ("websocket", {"webui": True, "locale": "en"}, "Stopped."),
    ("websocket", {"locale": "en"}, "Stopped."),
    ("telegram", {"locale": "zh-CN"}, "已停止。"),
])
async def test_cmd_stop_feedback_by_channel(count, channel, metadata, expected):
    loop = MagicMock(_cancel_active_tasks=AsyncMock(return_value=count))
    msg = InboundMessage(channel=channel, sender_id="user", chat_id="chat", content="/stop", metadata=metadata)
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, loop=loop)

    result = await cmd_stop(ctx)

    loop._cancel_active_tasks.assert_awaited_once_with(msg.session_key)
    assert result.content == ""
    assert isinstance(result.event, CommandResultEvent) and result.event.command == "/stop"
    assert (result.channel, result.chat_id, message_text(result)) == (msg.channel, msg.chat_id, expected)
