from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import DiscordChannel
from nanobot.channels.discord import DiscordConfig


def _make_channel(*, group_policy: str = "mention") -> DiscordChannel:
    bus = MessageBus()
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            token="test-token",
            allow_from=["*"],
            group_policy=group_policy,
        ),
        bus,
    )
    channel._bot_user_id = "999"
    channel._start_typing = AsyncMock()
    return channel


def _make_payload(content: str, guild_id: str) -> dict:
    return {
        "id": "456",
        "author": {"id": "111", "bot": False},
        "channel_id": "222",
        "content": content,
        "attachments": [],
        "guild_id": guild_id,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_content"),
    [
        ("<@999> /new", "/new"),
        ("<@!999> /help", "/help"),
        ("/help <@!999>", "/help"),
        ("<@!999> hello world", "hello world")
    ],
)
async def test_handle_message_create_with_mention_policy(
    content: str,
    expected_content: str,
) -> None:
    channel = _make_channel(group_policy="mention")

    await channel._handle_message_create(_make_payload(content=content, guild_id="123"))

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "111"
    assert msg.chat_id == "222"
    assert msg.content == expected_content
    assert msg.media == []
    assert msg.metadata == {
        "message_id": "456",
        "guild_id": "123",
        "reply_to": None,
    }


@pytest.mark.asyncio
async def test_guild_message_without_mention_is_ignored_in_mention_mode() -> None:
    channel = _make_channel(group_policy="mention")

    await channel._handle_message_create(_make_payload(content="/new", guild_id="123"))

    channel._start_typing.assert_not_awaited()
    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_content"),
    [
        ("/new", "/new"),
        ("hello world", "hello world")
    ],
)
async def test_handle_message_create_with_open_policy(content, expected_content) -> None:
    channel = _make_channel(group_policy="open")

    await channel._handle_message_create(_make_payload(content=content, guild_id="123"))

    msg = await channel.bus.consume_inbound()
    assert msg.content == expected_content