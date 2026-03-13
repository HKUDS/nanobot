from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.wecom import WecomChannel
from nanobot.config.schema import WecomConfig


@pytest.mark.asyncio
async def test_wecom_content_progress_reuses_stream_id_and_finishes_on_final() -> None:
    channel = WecomChannel(WecomConfig(enabled=True), MessageBus())
    channel._client = SimpleNamespace(reply_stream=AsyncMock())
    channel._chat_frames["chat-1"] = {"frame": "x"}
    channel._generate_req_id = lambda _prefix: "stream-fixed"

    await channel.send(
        OutboundMessage(
            channel="wecom",
            chat_id="chat-1",
            content="he",
            metadata={"_progress": True, "_progress_kind": "content"},
        )
    )
    await channel.send(
        OutboundMessage(
            channel="wecom",
            chat_id="chat-1",
            content="llo",
            metadata={"_progress": True, "_progress_kind": "content"},
        )
    )
    await channel.send(
        OutboundMessage(
            channel="wecom",
            chat_id="chat-1",
            content="hello",
        )
    )

    calls = channel._client.reply_stream.await_args_list
    assert len(calls) == 3
    assert calls[0].kwargs["finish"] is False
    assert calls[1].kwargs["finish"] is False
    assert calls[2].kwargs["finish"] is True

    assert calls[0].args[1] == "stream-fixed"
    assert calls[1].args[1] == "stream-fixed"
    assert calls[2].args[1] == "stream-fixed"
    assert channel._active_stream_ids == {}


@pytest.mark.asyncio
async def test_wecom_non_content_progress_uses_one_shot_stream() -> None:
    channel = WecomChannel(WecomConfig(enabled=True), MessageBus())
    channel._client = SimpleNamespace(reply_stream=AsyncMock())
    channel._chat_frames["chat-1"] = {"frame": "x"}
    channel._generate_req_id = lambda _prefix: "stream-fixed"

    await channel.send(
        OutboundMessage(
            channel="wecom",
            chat_id="chat-1",
            content="thinking...",
            metadata={"_progress": True, "_progress_kind": "reasoning"},
        )
    )

    channel._client.reply_stream.assert_awaited_once()
    call = channel._client.reply_stream.await_args_list[0]
    assert call.args[1] == "stream-fixed"
    assert call.kwargs["finish"] is True
    assert channel._active_stream_ids == {}
