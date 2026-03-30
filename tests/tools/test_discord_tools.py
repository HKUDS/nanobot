"""Tests for Discord API tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.tools.discord_tools import (
    DiscordCreateChannelTool,
    DiscordCreateEmbedTool,
    DiscordCreateThreadTool,
    DiscordManageRolesTool,
    DiscordPinMessageTool,
    DiscordPollTool,
    DiscordSendTool,
)


async def test_discord_send_posts_plain_text():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=200,
        content=b'{"id": "111"}',
        json=MagicMock(return_value={"id": "111"}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordSendTool(mock_http, "fake_token")
    result = await tool.execute(channel_id="123", content="hello")
    assert "111" in result
    mock_http.request.assert_called_once()
    call_kwargs = mock_http.request.call_args
    assert call_kwargs[0][0] == "POST"
    assert "/channels/123/messages" in call_kwargs[0][1]


async def test_discord_send_requires_content_or_embed():
    mock_http = AsyncMock()
    tool = DiscordSendTool(mock_http, "fake_token")
    result = await tool.execute(channel_id="123")
    assert "Error" in result
    mock_http.request.assert_not_called()


async def test_discord_manage_roles_add():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=204,
        content=b"",
        json=MagicMock(return_value={}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordManageRolesTool(mock_http, "token")
    result = await tool.execute(guild_id="g1", user_id="u1", role_id="r1", action="add")
    assert "success" in result.lower() or "added" in result.lower()
    call = mock_http.request.call_args[0]
    assert call[0] == "PUT"
    assert "/guilds/g1/members/u1/roles/r1" in call[1]


async def test_discord_manage_roles_remove():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=204,
        content=b"",
        json=MagicMock(return_value={}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordManageRolesTool(mock_http, "token")
    await tool.execute(guild_id="g1", user_id="u1", role_id="r1", action="remove")
    call = mock_http.request.call_args[0]
    assert call[0] == "DELETE"


async def test_discord_poll_validates_min_answers():
    mock_http = AsyncMock()
    tool = DiscordPollTool(mock_http, "token")
    result = await tool.execute(channel_id="123", question="Vote?", answers=["only one"])
    assert "Error" in result or "error" in result.lower()
    mock_http.request.assert_not_called()


async def test_discord_pin_message_uses_put():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=204,
        content=b"",
        json=MagicMock(return_value={}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordPinMessageTool(mock_http, "token")
    await tool.execute(channel_id="c1", message_id="m1")
    call = mock_http.request.call_args[0]
    assert call[0] == "PUT"
    assert "/channels/c1/pins/m1" in call[1]


async def test_discord_create_thread_from_message():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=200,
        content=b'{"id": "t1", "name": "my-thread"}',
        json=MagicMock(return_value={"id": "t1", "name": "my-thread"}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordCreateThreadTool(mock_http, "token")
    result = await tool.execute(channel_id="c1", name="my-thread", message_id="msg1")
    assert "t1" in result
    call = mock_http.request.call_args[0]
    assert "/messages/msg1/threads" in call[1]


async def test_discord_create_embed_sends_rich_embed():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=200,
        content=b'{"id": "e1"}',
        json=MagicMock(return_value={"id": "e1"}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordCreateEmbedTool(mock_http, "token")
    result = await tool.execute(
        channel_id="c1",
        title="Hello",
        description="World",
        footer="Bot",
        fields=[{"name": "f1", "value": "v1"}],
    )
    assert "e1" in result
    call = mock_http.request.call_args[0]
    assert call[0] == "POST"
    assert "/channels/c1/messages" in call[1]


async def test_discord_create_embed_rejects_private_image_url(monkeypatch):
    mock_http = AsyncMock()
    tool = DiscordCreateEmbedTool(mock_http, "token")
    # Patch validate_url_target to simulate SSRF rejection
    import nanobot.security.network as net_mod

    monkeypatch.setattr(net_mod, "validate_url_target", lambda url: (False, "private IP blocked"))
    result = await tool.execute(channel_id="c1", title="t", image_url="http://169.254.169.254/")
    assert "Error" in result
    assert "image_url" in result
    mock_http.request.assert_not_called()


async def test_discord_create_channel_posts_to_guild():
    mock_http = AsyncMock()
    mock_http.request.return_value = MagicMock(
        status_code=200,
        content=b'{"id": "ch1", "name": "general"}',
        json=MagicMock(return_value={"id": "ch1", "name": "general"}),
        raise_for_status=MagicMock(),
    )
    tool = DiscordCreateChannelTool(mock_http, "token")
    result = await tool.execute(guild_id="g1", name="general")
    assert "ch1" in result
    call = mock_http.request.call_args[0]
    assert call[0] == "POST"
    assert "/guilds/g1/channels" in call[1]
