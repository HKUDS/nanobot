import asyncio
import json
import tempfile
from types import SimpleNamespace
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
        WeixinConfig(
            enabled=True,
            allow_from=["*"],
            state_dir=tempfile.mkdtemp(prefix="nanobot-weixin-test-"),
        ),
        bus,
    )
    return channel, bus


def test_make_headers_includes_route_tag_when_configured() -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], route_tag=123),
        bus,
    )
    channel._token = "token"

    headers = channel._make_headers()

    assert headers["Authorization"] == "Bearer token"
    assert headers["SKRouteTag"] == "123"


def test_save_and_load_state_persists_context_tokens(tmp_path) -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )
    channel._token = "token"
    channel._get_updates_buf = "cursor"
    channel._context_tokens = {"wx-user": "ctx-1"}

    channel._save_state()

    saved = json.loads((tmp_path / "account.json").read_text())
    assert saved["context_tokens"] == {"wx-user": "ctx-1"}

    restored = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )

    assert restored._load_state() is True
    assert restored._context_tokens == {"wx-user": "ctx-1"}


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
async def test_process_message_persists_context_token_to_state_file(tmp_path) -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2b",
            "from_user_id": "wx-user",
            "context_token": "ctx-2b",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "ping"}},
            ],
        }
    )

    saved = json.loads((tmp_path / "account.json").read_text())
    assert saved["context_tokens"] == {"wx-user": "ctx-2b"}


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
async def test_send_does_not_send_when_session_is_paused() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-2"
    channel._pause_session(60)
    channel._send_text = AsyncMock()

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_pauses_session_on_expired_errcode() -> None:
    channel, _bus = _make_channel()
    channel._client = SimpleNamespace(timeout=None)
    channel._token = "token"
    channel._api_post = AsyncMock(return_value={"ret": 0, "errcode": -14, "errmsg": "expired"})

    await channel._poll_once()

    assert channel._session_pause_remaining_s() > 0


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
