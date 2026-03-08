from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import DiscordChannel
from nanobot.config.schema import DiscordConfig


def _make_channel(*, reply_to_message: bool = False) -> DiscordChannel:
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True, token="token", allow_from=["*"], reply_to_message=reply_to_message
        ),
        MessageBus(),
    )
    channel._http = object()
    channel._stop_typing = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_send_implicitly_replies_from_inbound_metadata_when_enabled() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(return_value=True)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            metadata={"message_id": "inbound-1"},
        )
    )

    payload = channel._send_payload.await_args_list[0].args[2]
    assert payload["message_reference"] == {"message_id": "inbound-1"}
    assert payload["allowed_mentions"] == {"replied_user": False}


@pytest.mark.asyncio
async def test_send_does_not_implicitly_reply_when_disabled() -> None:
    channel = _make_channel(reply_to_message=False)
    channel._send_file = AsyncMock(return_value=True)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            metadata={"message_id": "inbound-1"},
        )
    )

    payload = channel._send_payload.await_args_list[0].args[2]
    assert "message_reference" not in payload
    assert "allowed_mentions" not in payload


@pytest.mark.asyncio
async def test_send_prefers_explicit_reply_target_over_inbound_metadata() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(return_value=True)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            reply_to="explicit-1",
            metadata={"message_id": "inbound-1"},
        )
    )

    payload = channel._send_payload.await_args_list[0].args[2]
    assert payload["message_reference"] == {"message_id": "explicit-1"}
    assert payload["allowed_mentions"] == {"replied_user": False}


@pytest.mark.asyncio
async def test_send_passes_computed_reply_target_to_attachment_path() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(return_value=True)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            media=["/tmp/file.txt"],
            metadata={"message_id": "inbound-1"},
        )
    )

    assert channel._send_file.await_args_list[0].kwargs["reply_to"] == "inbound-1"


@pytest.mark.asyncio
async def test_send_uses_reply_anchor_only_once_across_successful_attachments() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(side_effect=[True, True])
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            media=["/tmp/file1.txt", "/tmp/file2.txt"],
            metadata={"message_id": "inbound-1"},
        )
    )

    assert channel._send_file.await_args_list[0].kwargs["reply_to"] == "inbound-1"
    assert channel._send_file.await_args_list[1].kwargs["reply_to"] is None


@pytest.mark.asyncio
async def test_send_suppresses_text_reply_anchor_after_successful_attachment_reply() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(return_value=True)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            media=["/tmp/file1.txt"],
            metadata={"message_id": "inbound-1"},
        )
    )

    payload = channel._send_payload.await_args_list[0].args[2]
    assert "message_reference" not in payload
    assert "allowed_mentions" not in payload


@pytest.mark.asyncio
async def test_send_falls_back_to_text_reply_anchor_after_attachment_failure() -> None:
    channel = _make_channel(reply_to_message=True)
    channel._send_file = AsyncMock(return_value=False)
    channel._send_payload = AsyncMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="hello",
            media=["/tmp/file1.txt"],
            metadata={"message_id": "inbound-1"},
        )
    )

    payload = channel._send_payload.await_args_list[0].args[2]
    assert payload["message_reference"] == {"message_id": "inbound-1"}
    assert payload["allowed_mentions"] == {"replied_user": False}
