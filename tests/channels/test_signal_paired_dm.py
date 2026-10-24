"""Approved Signal senders must reach normal DM content handling."""

from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.signal.runtime import SignalChannel, SignalConfig
from nanobot.pairing import approve_code, generate_code


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_id", ["+1234567890|uuid-example", "+1234567890", "1234567890", "uuid-example"])
async def test_paired_dm_preserves_content_and_metadata(tmp_path, monkeypatch, approved_id):
    monkeypatch.setattr("nanobot.pairing.store.get_data_dir", lambda: tmp_path)
    code = generate_code("signal", approved_id)
    assert approve_code(code) == ("signal", approved_id)
    bus = MessageBus()
    channel = SignalChannel(SignalConfig(phone_number="+9999999999"), bus)
    channel._start_typing = AsyncMock()

    await channel._handle_data_message(
        "+1234567890|uuid-example", "+1234567890",
        {"message": "Keep this question intact", "timestamp": 123}, "Sender",
    )

    delivered = await bus.consume_inbound()
    assert delivered.content == "Keep this question intact"
    assert delivered.metadata["timestamp"] == 123
    assert delivered.metadata["sender_name"] == "Sender"
    channel._start_typing.assert_awaited_once_with("+1234567890")


@pytest.mark.asyncio
async def test_pairing_does_not_enable_disabled_dms_or_unlisted_groups(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.pairing.store.get_data_dir", lambda: tmp_path)
    approve_code(generate_code("signal", "+1234567890"))
    bus = MessageBus()
    channel = SignalChannel(SignalConfig(
        phone_number="+9999999999", dm={"enabled": False},
        group={"enabled": True, "requireMention": False},
    ), bus)
    channel._start_typing = AsyncMock()

    await channel._handle_data_message(
        "+1234567890", "+1234567890", {"message": "DM"}, "Sender",
    )
    await channel._handle_data_message(
        "+1234567890", "+1234567890",
        {"message": "Group", "groupInfo": {"groupId": "unlisted-group"}}, "Sender",
    )

    assert bus.inbound_size == 0
    channel._start_typing.assert_not_awaited()
