"""Tests for the Discord channel implementation."""

from __future__ import annotations

import pytest

try:
    import discord
except ImportError:
    pytest.skip("discord.py not installed", allow_module_level=True)

from unittest.mock import AsyncMock, MagicMock

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import DiscordChannel, DiscordConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_discord_channel(
    allow_from: list[str] | None = None,
    group_policy: str = "mention",
    slash_commands_enabled: bool = True,
) -> tuple[DiscordChannel, MessageBus]:
    """Return a DiscordChannel + MessageBus with no real Discord client."""
    bus = MessageBus()
    cfg = DiscordConfig(
        enabled=True,
        token="test-token",
        allow_from=allow_from or ["*"],
        group_policy=group_policy,  # type: ignore[arg-type]
        slash_commands_enabled=slash_commands_enabled,
    )
    channel = DiscordChannel(cfg, bus)
    return channel, bus


def _make_discord_message(
    author_id: int = 123,
    channel_id: int = 456,
    content: str = "hello",
    author_bot: bool = False,
    guild_id: int | None = None,
    mentions: list | None = None,
) -> MagicMock:
    """Build a fake discord.Message MagicMock."""
    message = MagicMock(spec=discord.Message)
    message.author.bot = author_bot
    message.author.id = author_id
    message.channel.id = channel_id
    message.content = content
    message.attachments = []
    message.mentions = mentions or []
    message.reference = None

    # typing() must be an async context manager
    async_ctx = AsyncMock()
    async_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    async_ctx.__aexit__ = AsyncMock(return_value=False)
    message.channel.typing = MagicMock(return_value=async_ctx)

    if guild_id is not None:
        guild = MagicMock()
        guild.id = guild_id
        message.guild = guild
    else:
        message.guild = None

    return message


def _make_interaction(
    channel_id: int = 789,
    user_id: int = 123,
    guild_id: int | None = None,
) -> MagicMock:
    """Build a fake discord.Interaction MagicMock."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel_id = channel_id
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.guild_id = guild_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ---------------------------------------------------------------------------
# Group 1 — Config tests
# ---------------------------------------------------------------------------

def test_discord_config_defaults() -> None:
    cfg = DiscordConfig()
    assert cfg.slash_commands_enabled is True
    assert cfg.threads_per_conversation is False
    assert cfg.ephemeral_commands is True
    assert cfg.admin_role_ids == []
    assert cfg.application_id == ""
    assert cfg.guild_ids == []


def test_discord_config_snake_case() -> None:
    cfg = DiscordConfig.model_validate(
        {"enabled": True, "slash_commands_enabled": False, "admin_role_ids": ["123"]}
    )
    assert cfg.enabled is True
    assert cfg.slash_commands_enabled is False
    assert cfg.admin_role_ids == ["123"]


def test_discord_config_camel_case() -> None:
    cfg = DiscordConfig.model_validate(
        {"enabled": True, "slashCommandsEnabled": False, "adminRoleIds": ["456"]}
    )
    assert cfg.enabled is True
    assert cfg.slash_commands_enabled is False
    assert cfg.admin_role_ids == ["456"]


# ---------------------------------------------------------------------------
# Group 2 — Message handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_allowed_sender() -> None:
    channel, bus = _make_discord_channel(allow_from=["123"])
    channel._bot_user_id = "999"
    message = _make_discord_message(author_id=123, guild_id=None)
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 1


@pytest.mark.asyncio
async def test_handle_message_denied_sender() -> None:
    channel, bus = _make_discord_channel(allow_from=["123"])
    channel._bot_user_id = "999"
    message = _make_discord_message(author_id=456, guild_id=None)
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 0


@pytest.mark.asyncio
async def test_handle_message_bot_ignored() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"])
    message = _make_discord_message(author_bot=True, guild_id=None)
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 0


@pytest.mark.asyncio
async def test_handle_message_group_mention_policy() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"], group_policy="mention")
    channel._bot_user_id = "999"
    # Guild message, no mention
    message = _make_discord_message(author_id=123, channel_id=456, guild_id=111, mentions=[])
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 0


@pytest.mark.asyncio
async def test_handle_message_group_open_policy() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"], group_policy="open")
    channel._bot_user_id = "999"
    message = _make_discord_message(author_id=123, channel_id=456, guild_id=111)
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 1


@pytest.mark.asyncio
async def test_handle_message_dm_bypasses_group_policy() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"], group_policy="mention")
    channel._bot_user_id = "999"
    # DM: guild=None
    message = _make_discord_message(author_id=123, channel_id=456, guild_id=None)
    await channel._handle_message_create(message)
    assert bus.inbound.qsize() == 1


# ---------------------------------------------------------------------------
# Group 3 — send() tests
# ---------------------------------------------------------------------------

def _make_channel_with_mock_client() -> tuple[DiscordChannel, MessageBus, MagicMock]:
    """Return channel + bus + fake_channel mock wired to client."""
    channel, bus = _make_discord_channel()

    fake_discord_channel = MagicMock()
    fake_discord_channel.send = AsyncMock()

    mock_client = MagicMock()
    mock_client.get_channel = MagicMock(return_value=fake_discord_channel)
    mock_client.fetch_channel = AsyncMock(return_value=fake_discord_channel)

    channel._client = mock_client
    return channel, bus, fake_discord_channel


@pytest.mark.asyncio
async def test_send_plain_text() -> None:
    channel, bus, fake_discord_channel = _make_channel_with_mock_client()
    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))
    fake_discord_channel.send.assert_called_once()
    call_kwargs = fake_discord_channel.send.call_args
    assert call_kwargs.kwargs.get("content") == "hello"


@pytest.mark.asyncio
async def test_send_chunked_long_message() -> None:
    channel, bus, fake_discord_channel = _make_channel_with_mock_client()
    long_content = "x" * 2500
    await channel.send(OutboundMessage(channel="discord", chat_id="123", content=long_content))
    assert fake_discord_channel.send.call_count == 2


@pytest.mark.asyncio
async def test_send_with_reply_to() -> None:
    channel, bus, fake_discord_channel = _make_channel_with_mock_client()
    await channel.send(
        OutboundMessage(channel="discord", chat_id="123", content="hi", reply_to="555")
    )
    fake_discord_channel.send.assert_called_once()
    call_kwargs = fake_discord_channel.send.call_args.kwargs
    reference = call_kwargs.get("reference")
    assert reference is not None
    assert reference.message_id == 555


@pytest.mark.asyncio
async def test_send_with_interaction_followup() -> None:
    channel, bus, fake_discord_channel = _make_channel_with_mock_client()
    mock_interaction = _make_interaction(channel_id=123)
    channel._pending_interactions["123"] = mock_interaction

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="response"))

    mock_interaction.followup.send.assert_called_once()
    # channel.send should NOT be called when using followup
    fake_discord_channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_clears_pending_interaction() -> None:
    channel, bus, fake_discord_channel = _make_channel_with_mock_client()
    mock_interaction = _make_interaction(channel_id=123)
    channel._pending_interactions["123"] = mock_interaction

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="done"))

    assert "123" not in channel._pending_interactions


# ---------------------------------------------------------------------------
# Group 4 partial — Slash command injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slash_stop_injects_to_bus() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"])
    interaction = _make_interaction(channel_id=789, user_id=123, guild_id=None)

    await channel._inject_slash_as_message(interaction, "/stop")

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    assert bus.inbound.qsize() == 1
    msg = await bus.consume_inbound()
    assert msg.content == "/stop"


@pytest.mark.asyncio
async def test_slash_new_injects_to_bus() -> None:
    channel, bus = _make_discord_channel(allow_from=["*"])
    interaction = _make_interaction(channel_id=789, user_id=123, guild_id=None)

    await channel._inject_slash_as_message(interaction, "/new")

    assert bus.inbound.qsize() == 1
    msg = await bus.consume_inbound()
    assert msg.content == "/new"
