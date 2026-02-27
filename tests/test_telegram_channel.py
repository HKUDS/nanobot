from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


def _make_update(
    *,
    text: str = "",
    chat_type: str = "group",
    chat_id: int = -10001,
    user_id: int = 123,
    username: str = "alice",
    first_name: str = "Alice",
    reply_to_user_id: int | None = None,
):
    user = SimpleNamespace(id=user_id, username=username, first_name=first_name, last_name="")
    reply_to = None
    if reply_to_user_id is not None:
        reply_to = SimpleNamespace(from_user=SimpleNamespace(id=reply_to_user_id))
    message = SimpleNamespace(
        chat_id=chat_id,
        chat=SimpleNamespace(type=chat_type),
        text=text,
        caption=None,
        photo=[],
        voice=None,
        audio=None,
        document=None,
        reply_to_message=reply_to,
        message_id=42,
    )
    return SimpleNamespace(message=message, effective_user=user)


@pytest.mark.asyncio
async def test_group_mention_policy_buffers_and_flushes_history(monkeypatch) -> None:
    cfg = TelegramConfig(
        enabled=True,
        token="token",
        group_policy="mention",
        group_history_on_mention=8,
        mention_by_reply=True,
    )
    channel = TelegramChannel(cfg, MessageBus())
    channel._bot_username = "nanobot"
    channel._bot_user_id = 999

    monkeypatch.setattr(channel, "_start_typing", lambda _chat_id: None)

    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    await channel._on_message(
        _make_update(text="hello everyone", user_id=101, username="alice", first_name="Alice"),
        None,
    )
    assert captured == []

    await channel._on_message(
        _make_update(text="@nanobot what should we do?", user_id=202, username="bob", first_name="Bob"),
        None,
    )
    assert len(captured) == 1
    payload = captured[0]
    assert payload["chat_id"] == "-10001"
    assert "Recent group messages before mention:" in payload["content"]
    assert "Alice (@alice, id:101): hello everyone" in payload["content"]
    assert "Current message:" in payload["content"]
    assert "Bob (@bob, id:202): what should we do?" in payload["content"]
    assert payload["metadata"]["was_mentioned"] is True
    assert payload["metadata"]["group_policy"] == "mention"


@pytest.mark.asyncio
async def test_group_open_policy_includes_sender_identity(monkeypatch) -> None:
    cfg = TelegramConfig(enabled=True, token="token", group_policy="open")
    channel = TelegramChannel(cfg, MessageBus())
    channel._bot_username = "nanobot"
    channel._bot_user_id = 999

    monkeypatch.setattr(channel, "_start_typing", lambda _chat_id: None)

    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    await channel._on_message(
        _make_update(text="status update", user_id=303, username="carol", first_name="Carol"),
        None,
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["content"] == "Carol (@carol, id:303): status update"
    assert payload["metadata"]["is_group"] is True
    assert payload["metadata"]["group_policy"] == "open"


@pytest.mark.asyncio
async def test_private_chat_not_affected_by_group_mention_policy(monkeypatch) -> None:
    cfg = TelegramConfig(enabled=True, token="token", group_policy="mention")
    channel = TelegramChannel(cfg, MessageBus())
    channel._bot_username = "nanobot"
    channel._bot_user_id = 999

    monkeypatch.setattr(channel, "_start_typing", lambda _chat_id: None)

    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    await channel._on_message(
        _make_update(
            text="hello from dm",
            chat_type="private",
            chat_id=777,
            user_id=404,
            username="dave",
            first_name="Dave",
        ),
        None,
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["chat_id"] == "777"
    assert payload["content"] == "hello from dm"
    assert payload["metadata"]["is_group"] is False
    assert payload["metadata"]["was_mentioned"] is False


@pytest.mark.asyncio
async def test_group_reply_to_bot_counts_as_mention(monkeypatch) -> None:
    cfg = TelegramConfig(
        enabled=True,
        token="token",
        group_policy="mention",
        group_history_on_mention=8,
        mention_by_reply=True,
    )
    channel = TelegramChannel(cfg, MessageBus())
    channel._bot_username = "nanobot"
    channel._bot_user_id = 999

    monkeypatch.setattr(channel, "_start_typing", lambda _chat_id: None)

    captured: list[dict] = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    await channel._on_message(
        _make_update(
            text="agree",
            user_id=505,
            username="erin",
            first_name="Erin",
            reply_to_user_id=999,
        ),
        None,
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["metadata"]["was_mentioned"] is True
    assert payload["content"] == "Erin (@erin, id:505): agree"
