"""Telegram per-chat and per-topic group policy overrides.

``channels.telegram.groupPolicyOverrides`` lets one bot serve several forum
topics with different reply behavior: keep the channel-wide policy ``open``
and silence a single announcement topic with ``"mention"``, or the other way
around. Keys are either ``"<chat_id>"`` (whole chat) or
``"<chat_id>:<thread_id>"`` (one forum topic); unlisted scopes fall back to
the channel-wide ``groupPolicy``.

The topic key is ``chat_id``-qualified because Telegram forum topics do not
have their own chat id — every topic shares the parent supergroup's ``chat_id``
and is distinguished only by ``message_thread_id``.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("telegram")

from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram.runtime import TelegramChannel, TelegramConfig

CHAT = "-1001668715626"


def _make_channel(**config_kwargs: Any) -> TelegramChannel:
    config = TelegramConfig(token="test_token", **config_kwargs)
    return TelegramChannel(config, MessageBus())


class _Chat:
    def __init__(self, chat_type: str = "supergroup") -> None:
        self.type = chat_type


class _Message:
    """Minimal stand-in for a telegram.Message."""

    def __init__(
        self,
        chat_id: str = CHAT,
        *,
        chat_type: str = "supergroup",
        message_thread_id: int | None = None,
    ) -> None:
        self.chat_id = int(chat_id)
        self.chat = _Chat(chat_type)
        self.message_thread_id = message_thread_id


def test_effective_policy_falls_back_to_channel_default() -> None:
    channel = _make_channel(group_policy="mention")
    assert channel._effective_group_policy(_Message()) == "mention"

    channel = _make_channel(group_policy="open")
    assert channel._effective_group_policy(_Message()) == "open"


def test_chat_level_override_wins_over_channel_default() -> None:
    channel = _make_channel(group_policy="open", group_policy_overrides={CHAT: "mention"})
    assert channel._effective_group_policy(_Message()) == "mention"


def test_topic_override_wins_over_chat_level_override() -> None:
    channel = _make_channel(
        group_policy="open",
        group_policy_overrides={CHAT: "open", f"{CHAT}:7819": "mention"},
    )
    assert channel._effective_group_policy(_Message(message_thread_id=7819)) == "mention"
    # A different topic in the same chat keeps the chat-level policy.
    assert channel._effective_group_policy(_Message(message_thread_id=7818)) == "open"


def test_topic_override_does_not_leak_to_other_chats() -> None:
    channel = _make_channel(
        group_policy="open",
        group_policy_overrides={f"{CHAT}:7819": "mention"},
    )
    other_chat = _Message(chat_id="-1009999999999", message_thread_id=7819)
    assert channel._effective_group_policy(other_chat) == "open"


def test_chat_override_applies_without_a_topic() -> None:
    """A non-forum group message has no thread id but still honors chat overrides."""
    channel = _make_channel(group_policy="open", group_policy_overrides={CHAT: "mention"})
    message = _Message(chat_type="group", message_thread_id=None)
    assert channel._effective_group_policy(message) == "mention"


@pytest.mark.asyncio
async def test_silenced_topic_ignores_plain_messages() -> None:
    """With an open channel and a silenced topic, plain chatter is ignored."""
    channel = _make_channel(
        group_policy="open",
        group_policy_overrides={f"{CHAT}:7819": "mention"},
    )
    channel._bot_id = 6826165590
    channel._bot_username = "DogalyirBot"
    message = _Message(message_thread_id=7819)
    message.text = "buenos dias equipo"
    message.caption = None
    message.entities = None

    assert await channel._is_group_message_for_bot(message) is False


@pytest.mark.asyncio
async def test_unsilenced_topic_still_answers_plain_messages() -> None:
    channel = _make_channel(
        group_policy="open",
        group_policy_overrides={f"{CHAT}:7819": "mention"},
    )
    channel._bot_id = 6826165590
    channel._bot_username = "DogalyirBot"
    message = _Message(message_thread_id=7818)
    message.text = "buenos dias equipo"
    message.caption = None
    message.entities = None

    assert await channel._is_group_message_for_bot(message) is True
