from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class _DummyChannel(BaseChannel):
    name = "dummy"
    _sent: list[OutboundMessage]

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._sent = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self._sent.append(msg)


def test_is_allowed_requires_exact_match() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=["allow@email.com"]), MessageBus())

    assert channel.is_allowed("allow@email.com") is True
    assert channel.is_allowed("attacker|allow@email.com") is False


def test_is_allowed_supports_dict_allow_from_alias() -> None:
    channel = _DummyChannel({"allowFrom": ["alice"]}, MessageBus())

    assert channel.is_allowed("alice") is True


def test_is_allowed_denies_empty_dict_allow_from() -> None:
    channel = _DummyChannel({"allow_from": []}, MessageBus())

    assert channel.is_allowed("alice") is False


def test_is_allowed_handles_none_allow_from() -> None:
    channel = _DummyChannel({"allow_from": None}, MessageBus())
    assert channel.is_allowed("alice") is False

    channel2 = _DummyChannel({"allowFrom": None}, MessageBus())
    assert channel2.is_allowed("alice") is False


def test_is_allowed_star_allows_all() -> None:
    channel = _DummyChannel({"allowFrom": ["*"]}, MessageBus())
    assert channel.is_allowed("anyone") is True


def test_is_allowed_pairing_fallback(monkeypatch) -> None:
    channel = _DummyChannel({"allowFrom": []}, MessageBus())
    monkeypatch.setattr(
        "nanobot.channels.base.is_approved", lambda _ch, sid: sid == "paired"
    )
    assert channel.is_allowed("paired") is True
    assert channel.is_allowed("unknown") is False


@pytest.mark.asyncio
async def test_handle_message_dm_sends_pairing_code(monkeypatch) -> None:
    channel = _DummyChannel({"allowFrom": []}, MessageBus())
    monkeypatch.setattr(
        "nanobot.channels.base.generate_code", lambda _ch, sid: "ABCD-EFGH"
    )

    await channel._handle_message(
        sender_id="stranger", chat_id="chat1", content="hello", is_dm=True
    )

    assert len(channel._sent) == 1
    msg = channel._sent[0]
    assert "ABCD-EFGH" in msg.content
    assert msg.metadata.get("_pairing_code") == "ABCD-EFGH"


@pytest.mark.asyncio
async def test_handle_message_group_ignores_unknown() -> None:
    channel = _DummyChannel({"allowFrom": []}, MessageBus())

    await channel._handle_message(
        sender_id="stranger", chat_id="chat1", content="hello", is_dm=False
    )

    assert channel._sent == []


@pytest.mark.asyncio
async def test_handle_message_uses_authorization_id_without_changing_sender() -> None:
    bus = MessageBus()
    channel = _DummyChannel({"allowFrom": ["group@g.us"]}, bus)

    await channel._handle_message(
        sender_id="member-lid",
        authorization_id="group@g.us",
        chat_id="group@g.us",
        content="hello",
    )

    msg = await bus.consume_inbound()
    assert msg.sender_id == "member-lid"
    assert msg.chat_id == "group@g.us"


@pytest.mark.asyncio
async def test_handle_message_rejects_when_authorization_id_is_not_allowed() -> None:
    bus = MessageBus()
    channel = _DummyChannel({"allowFrom": ["member-lid"]}, bus)

    await channel._handle_message(
        sender_id="member-lid",
        authorization_id="other-group@g.us",
        chat_id="other-group@g.us",
        content="hello",
    )

    assert bus.inbound_size == 0


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel({"allowFrom": ["*"]}, bus)

        for _ in range(50):
            await channel._handle_message(sender_id="alice", chat_id="c1", content="hi")

        assert bus.inbound_size == 50

    @pytest.mark.asyncio
    async def test_blocks_sender_over_the_limit(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel(
            {"allowFrom": ["*"], "rate_limit_per_min": 2}, bus
        )

        for _ in range(5):
            await channel._handle_message(sender_id="alice", chat_id="c1", content="hi")

        assert bus.inbound_size == 2

    @pytest.mark.asyncio
    async def test_rate_limit_is_per_sender(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel(
            {"allowFrom": ["*"], "rate_limit_per_min": 1}, bus
        )

        await channel._handle_message(sender_id="alice", chat_id="c1", content="hi")
        await channel._handle_message(sender_id="bob", chat_id="c1", content="hi")
        await channel._handle_message(sender_id="alice", chat_id="c1", content="hi again")

        assert bus.inbound_size == 2

    @pytest.mark.asyncio
    async def test_dm_gets_a_single_cooldown_notice_not_a_reply_per_message(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel(
            {"allowFrom": ["*"], "rate_limit_per_min": 1}, bus
        )

        for _ in range(5):
            await channel._handle_message(
                sender_id="alice", chat_id="c1", content="hi", is_dm=True
            )

        assert bus.inbound_size == 1
        assert len(channel._sent) == 1
        assert "too quickly" in channel._sent[0].content

    @pytest.mark.asyncio
    async def test_group_chat_is_silently_dropped_without_cooldown_spam(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel(
            {"allowFrom": ["*"], "rate_limit_per_min": 1}, bus
        )

        for _ in range(5):
            await channel._handle_message(
                sender_id="alice", chat_id="c1", content="hi", is_dm=False
            )

        assert bus.inbound_size == 1
        assert channel._sent == []

    @pytest.mark.asyncio
    async def test_burst_limit_narrower_than_per_minute_still_applies(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel(
            {
                "allowFrom": ["*"],
                "rate_limit_per_min": 100,
                "rate_limit_burst": 2,
            },
            bus,
        )

        for _ in range(5):
            await channel._handle_message(sender_id="alice", chat_id="c1", content="hi")

        assert bus.inbound_size == 2

