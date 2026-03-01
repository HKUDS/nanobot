from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


def _make_channel() -> TelegramChannel:
    return TelegramChannel(
        TelegramConfig(enabled=True, token="test-token"),
        MessageBus(),
    )


@pytest.mark.asyncio
async def test_on_reaction_forwards_structured_event_with_preview(monkeypatch) -> None:
    channel = _make_channel()
    channel._cache_message("123", 99, "Deploy to prod after smoke tests pass.")

    captured = {}

    async def _fake_handle_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _fake_handle_message)

    reaction = SimpleNamespace(
        chat=SimpleNamespace(id=123, type="group"),
        message_id=99,
        user=SimpleNamespace(id=7, username="alice", first_name="Alice"),
        actor_chat=None,
        old_reaction=[],
        new_reaction=[SimpleNamespace(type="emoji", emoji="👍")],
    )
    update = SimpleNamespace(message_reaction=reaction)

    await channel._on_reaction(update, None)

    assert captured["sender_id"] == "7|alice"
    assert captured["chat_id"] == "123"
    assert captured["content"] == "[reaction] 👍 to message_id=99 on: Deploy to prod after smoke tests pass."
    assert captured["metadata"]["event_type"] == "reaction"
    assert captured["metadata"]["reacted_message_id"] == 99
    assert captured["metadata"]["reactions"] == [{"type": "emoji", "emoji": "👍"}]
    assert captured["metadata"]["reacted_message_preview"] == "Deploy to prod after smoke tests pass."
    assert captured["metadata"]["tg_user_id"] == 7


@pytest.mark.asyncio
async def test_send_caches_outbound_message_text() -> None:
    channel = _make_channel()

    class FakeBot:
        def __init__(self) -> None:
            self.sent_messages: list[tuple[int, str, str | None]] = []

        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None, reply_parameters=None):
            self.sent_messages.append((chat_id, text, parse_mode))
            return SimpleNamespace(message_id=321)

    fake_bot = FakeBot()
    channel._app = SimpleNamespace(bot=fake_bot)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Ship it",
        )
    )

    assert fake_bot.sent_messages == [(123, "Ship it", "HTML")]
    assert channel._get_cached_message("123", 321) == "Ship it"


def test_cache_is_lru_per_chat() -> None:
    channel = _make_channel()

    for idx in range(channel.MESSAGE_CACHE_SIZE + 1):
        channel._cache_message("chat-1", idx, f"message-{idx}")

    assert channel._get_cached_message("chat-1", 0) is None
    assert channel._get_cached_message("chat-1", channel.MESSAGE_CACHE_SIZE) == (
        f"message-{channel.MESSAGE_CACHE_SIZE}"
    )
