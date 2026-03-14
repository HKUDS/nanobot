import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import DiscordChannel, DiscordConfig, MAX_MESSAGE_LEN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message_create_payload(
    *,
    content: str = "hello",
    author_id: str = "12345",
    channel_id: str = "chan-1",
    guild_id: str | None = "guild-1",
    bot: bool = False,
    mentions: list[dict] | None = None,
    attachments: list[dict] | None = None,
    referenced_message: dict | None = None,
) -> dict:
    return {
        "id": "msg-1",
        "author": {"id": author_id, "bot": bot},
        "channel_id": channel_id,
        "guild_id": guild_id,
        "content": content,
        "mentions": mentions or [],
        "attachments": attachments or [],
        "referenced_message": referenced_message,
    }


_SENTINEL = object()


def _make_channel(*, allow_from=_SENTINEL, group_policy="mention", history_policy="recent"):
    config = DiscordConfig(
        enabled=True,
        token="fake-token",
        allow_from=["*"] if allow_from is _SENTINEL else allow_from,
        group_policy=group_policy,
        history_policy=history_policy,
    )
    return DiscordChannel(config, MessageBus())


# ---------------------------------------------------------------------------
# DiscordConfig defaults
# ---------------------------------------------------------------------------

def test_discord_config_defaults():
    cfg = DiscordConfig()
    assert cfg.enabled is False
    assert cfg.group_policy == "mention"
    assert cfg.history_policy == "recent"
    assert cfg.intents == 37377


def test_discord_config_from_dict():
    cfg = DiscordConfig.model_validate({
        "enabled": True,
        "token": "tok",
        "groupPolicy": "open",
        "historyPolicy": "chats",
    })
    assert cfg.group_policy == "open"
    assert cfg.history_policy == "chats"


# ---------------------------------------------------------------------------
# history_policy literals
# ---------------------------------------------------------------------------

def test_history_policy_defaults_to_recent():
    cfg = DiscordConfig()
    assert cfg.history_policy == "recent"


def test_history_policy_accepts_chats():
    cfg = DiscordConfig(history_policy="chats")
    assert cfg.history_policy == "chats"


def test_history_policy_rejects_invalid():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DiscordConfig(history_policy="invalid")


# ---------------------------------------------------------------------------
# ChannelsConfig history_policy
# ---------------------------------------------------------------------------

def test_channels_config_history_policy_defaults_to_recent():
    from nanobot.config.schema import ChannelsConfig
    cfg = ChannelsConfig()
    assert cfg.history_policy == "recent"


def test_channels_config_history_policy_accepts_chats():
    from nanobot.config.schema import ChannelsConfig
    cfg = ChannelsConfig(history_policy="chats")
    assert cfg.history_policy == "chats"


def test_channels_config_history_policy_camel_case():
    from nanobot.config.schema import ChannelsConfig
    cfg = ChannelsConfig.model_validate({"historyPolicy": "chats"})
    assert cfg.history_policy == "chats"


def test_channels_config_history_policy_rejects_invalid():
    from pydantic import ValidationError
    from nanobot.config.schema import ChannelsConfig
    with pytest.raises(ValidationError):
        ChannelsConfig(history_policy="bad")


# ---------------------------------------------------------------------------
# is_allowed
# ---------------------------------------------------------------------------

def test_is_allowed_wildcard():
    channel = _make_channel(allow_from=["*"])
    assert channel.is_allowed("anyone") is True


def test_is_allowed_specific_id():
    channel = _make_channel(allow_from=["12345"])
    assert channel.is_allowed("12345") is True
    assert channel.is_allowed("99999") is False


def test_is_allowed_empty_denies_all():
    channel = _make_channel(allow_from=[])
    assert channel.is_allowed("12345") is False


# ---------------------------------------------------------------------------
# group_policy: mention vs open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_group_policy_mention_ignores_unmentioned_message():
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "999"
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(content="hello everyone")
    await channel._handle_message_create(payload)

    assert handled == []


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_mentioned_message():
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "999"
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(
        content="<@999> hi",
        mentions=[{"id": "999"}],
    )
    await channel._handle_message_create(payload)

    assert len(handled) == 1


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_nickname_mention():
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "999"
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(content="<@!999> help")
    await channel._handle_message_create(payload)

    assert len(handled) == 1


@pytest.mark.asyncio
async def test_group_policy_open_accepts_plain_message():
    channel = _make_channel(group_policy="open")
    channel._bot_user_id = "999"
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(content="hello group")
    await channel._handle_message_create(payload)

    assert len(handled) == 1


# ---------------------------------------------------------------------------
# DM (no guild_id) always responds regardless of group_policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dm_responds_regardless_of_group_policy():
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "999"
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(content="hi in DM", guild_id=None)
    await channel._handle_message_create(payload)

    assert len(handled) == 1


# ---------------------------------------------------------------------------
# Bot messages ignored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bot_messages_are_ignored():
    channel = _make_channel(group_policy="open")
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(content="bot msg", bot=True)
    await channel._handle_message_create(payload)

    assert handled == []


# ---------------------------------------------------------------------------
# Metadata includes guild_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_passes_guild_id_in_metadata():
    channel = _make_channel(group_policy="open")
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(guild_id="g-42")
    await channel._handle_message_create(payload)

    assert len(handled) == 1
    assert handled[0]["metadata"]["guild_id"] == "g-42"


# ---------------------------------------------------------------------------
# reply_to from referenced_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_extracts_reply_to():
    channel = _make_channel(group_policy="open")
    handled = []
    channel._handle_message = AsyncMock(side_effect=lambda **kw: handled.append(kw))
    channel._http = AsyncMock()

    payload = _make_message_create_payload(
        referenced_message={"id": "ref-msg-42"},
    )
    await channel._handle_message_create(payload)

    assert len(handled) == 1
    assert handled[0]["metadata"]["reply_to"] == "ref-msg-42"


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_posts_to_discord_api():
    channel = _make_channel()
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None))
    channel._http = mock_http

    await channel.send(OutboundMessage(
        channel="discord",
        chat_id="chan-1",
        content="hello",
    ))

    mock_http.post.assert_called()
    call_args = mock_http.post.call_args
    assert "chan-1" in call_args.args[0]
    assert call_args.kwargs["json"]["content"] == "hello"


@pytest.mark.asyncio
async def test_send_includes_reply_reference():
    channel = _make_channel()
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None))
    channel._http = mock_http

    await channel.send(OutboundMessage(
        channel="discord",
        chat_id="chan-1",
        content="reply",
        reply_to="original-msg-id",
    ))

    call_args = mock_http.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["message_reference"]["message_id"] == "original-msg-id"


# ---------------------------------------------------------------------------
# default_config
# ---------------------------------------------------------------------------

def test_default_config_returns_camel_case_dict():
    cfg = DiscordChannel.default_config()
    assert "groupPolicy" in cfg
    assert "historyPolicy" in cfg
    assert cfg["historyPolicy"] == "recent"


# ---------------------------------------------------------------------------
# stop cleans up resources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_cancels_typing_tasks():
    channel = _make_channel()
    channel._http = AsyncMock()
    channel._http.aclose = AsyncMock()

    dummy = asyncio.get_event_loop().create_future()
    dummy.cancel()
    channel._typing_tasks["chan-1"] = asyncio.ensure_future(asyncio.sleep(999))

    await channel.stop()

    assert channel._typing_tasks == {}
    assert channel._http is None
    assert channel._running is False
