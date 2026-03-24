import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.weixin import (
    ITEM_IMAGE,
    ITEM_TEXT,
    MESSAGE_TYPE_BOT,
    WeixinChannel,
    WeixinConfig,
)


def _make_channel() -> tuple[WeixinChannel, MessageBus]:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"]),
        bus,
    )
    return channel, bus


@pytest.mark.asyncio
async def test_process_message_deduplicates_inbound_ids() -> None:
    channel, bus = _make_channel()
    msg = {
        "message_type": 1,
        "message_id": "m1",
        "from_user_id": "wx-user",
        "context_token": "ctx-1",
        "item_list": [
            {"type": ITEM_TEXT, "text_item": {"text": "hello"}},
        ],
    }

    await channel._process_message(msg)
    first = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await channel._process_message(msg)

    assert first.sender_id == "wx-user"
    assert first.chat_id == "wx-user"
    assert first.content == "hello"
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_process_message_caches_context_token_and_send_uses_it() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._send_text = AsyncMock()

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2",
            "from_user_id": "wx-user",
            "context_token": "ctx-2",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "ping"}},
            ],
        }
    )

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "pong", "ctx-2")


@pytest.mark.asyncio
async def test_process_message_extracts_media_and_preserves_paths() -> None:
    channel, bus = _make_channel()
    channel._download_media_item = AsyncMock(return_value="/tmp/test.jpg")

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m3",
            "from_user_id": "wx-user",
            "context_token": "ctx-3",
            "item_list": [
                {"type": ITEM_IMAGE, "image_item": {"media": {"encrypt_query_param": "x"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    assert "[image]" in inbound.content
    assert "/tmp/test.jpg" in inbound.content
    assert inbound.media == ["/tmp/test.jpg"]


@pytest.mark.asyncio
async def test_send_without_context_token_does_not_send_text() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._send_text = AsyncMock()

    await channel.send(
        type("Msg", (), {"chat_id": "unknown-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_skips_bot_messages() -> None:
    channel, bus = _make_channel()

    await channel._process_message(
        {
            "message_type": MESSAGE_TYPE_BOT,
            "message_id": "m4",
            "from_user_id": "wx-user",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "hello"}},
            ],
        }
    )

    assert bus.inbound_size == 0
