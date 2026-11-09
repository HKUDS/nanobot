from typing import Any

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.zalo import ZaloChannel, ZaloConfig


class _FakeBot:
    def __init__(self, token: str):
        self.token = token
        self.sent_messages: list[dict[str, Any]] = []
        self.chat_actions: list[dict[str, Any]] = []

    async def send_message(self, chat_id: str, text: str) -> None:
        self.sent_messages.append({"chat_id": chat_id, "text": text})

    async def send_chat_action(self, chat_id: str, action: Any) -> None:
        self.chat_actions.append({"chat_id": chat_id, "action": action})

    async def delete_webhook(self) -> None:
        pass


@pytest.mark.asyncio
async def test_zalo_config_validation() -> None:
    """Verify that ZaloConfig correctly validates and handles aliases."""
    config_dict = {
        "enabled": True,
        "botToken": "123:abc",
        "webhookSecret": "secret123",
        "webhookPath": "/custom/path",
        "allowFrom": ["user1", "user2"],
    }
    config = ZaloConfig.model_validate(config_dict)
    assert config.enabled is True
    assert config.bot_token == "123:abc"
    assert config.webhook_secret == "secret123"
    assert config.webhook_path == "/custom/path"
    assert config.allow_from == ["user1", "user2"]


@pytest.mark.asyncio
async def test_zalo_send_message() -> None:
    """Verify that ZaloChannel.send correctly calls the bot SDK."""
    config = {"enabled": True, "botToken": "123:abc"}
    bus = MessageBus()
    channel = ZaloChannel(config, bus)

    fake_bot = _FakeBot("123:abc")
    channel.bot = fake_bot

    outbound = OutboundMessage(channel="zalo", chat_id="user123", content="Hello from Nanobot!")

    await channel.send(outbound)

    assert len(fake_bot.sent_messages) == 1
    assert fake_bot.sent_messages[0]["chat_id"] == "user123"
    # Content is transformed (Unicode emphasis), but should contain the original text
    assert "Hello" in fake_bot.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_zalo_split_long_message() -> None:
    """Verify that ZaloChannel correctly splits long messages."""
    from nanobot.channels.zalo import MAX_TEXT_LEN

    config = {"enabled": True, "botToken": "123:abc"}
    bus = MessageBus()
    channel = ZaloChannel(config, bus)

    fake_bot = _FakeBot("123:abc")
    channel.bot = fake_bot

    # Create a message longer than MAX_TEXT_LEN
    long_content = "A" * (MAX_TEXT_LEN + 100)
    outbound = OutboundMessage(channel="zalo", chat_id="user123", content=long_content)

    await channel.send(outbound)

    assert len(fake_bot.sent_messages) == 2
    assert len(fake_bot.sent_messages[0]["text"]) <= MAX_TEXT_LEN
    assert len(fake_bot.sent_messages[1]["text"]) == 100
