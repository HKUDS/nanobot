from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext


@pytest.mark.parametrize("count", [0, 3])
@pytest.mark.parametrize(("channel", "metadata", "expected"), [
    ("websocket", {"webui": True}, None),
    ("websocket", {"locale": "en"}, "Stopped."),
    ("telegram", {"locale": "zh-CN"}, "已停止。"),
])
async def test_cmd_stop_feedback_by_channel(count, channel, metadata, expected):
    loop = MagicMock(_cancel_active_tasks=AsyncMock(return_value=count))
    msg = InboundMessage(channel=channel, sender_id="user", chat_id="chat", content="/stop", metadata=metadata)
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, loop=loop)

    result = await cmd_stop(ctx)

    loop._cancel_active_tasks.assert_awaited_once_with(msg.session_key)
    if expected is None:
        assert result is None
    else:
        assert (result.channel, result.chat_id, result.content) == (msg.channel, msg.chat_id, expected)
