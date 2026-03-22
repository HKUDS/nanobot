from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.napcat import NapCatChannel, NapCatConfig


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        import json

        self.sent.append(json.loads(payload))


@pytest.mark.asyncio
async def test_group_message_is_prefixed_with_username() -> None:
    channel = NapCatChannel(
        NapCatConfig(allow_from=["*"], group_policy="open", message_debounce_enabled=False),
        MessageBus(),
    )

    await channel._handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 1,
            "group_id": 42,
            "user_id": 100,
            "sender": {"nickname": "alice"},
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }
    )

    msg = await channel.bus.consume_inbound()
    assert msg.content == "alice: hello"
    assert msg.chat_id == "42"
    assert msg.metadata["sender_name"] == "alice"


@pytest.mark.asyncio
async def test_group_mention_policy_ignores_non_mentions() -> None:
    channel = NapCatChannel(
        NapCatConfig(allow_from=["*"], group_policy="mention", message_debounce_enabled=False),
        MessageBus(),
    )
    channel._self_id = "999"

    await channel._handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 1,
            "group_id": 42,
            "user_id": 100,
            "sender": {"nickname": "alice"},
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }
    )

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_group_mention_policy_accepts_at_bot() -> None:
    channel = NapCatChannel(
        NapCatConfig(allow_from=["*"], group_policy="mention", message_debounce_enabled=False),
        MessageBus(),
    )
    channel._self_id = "999"

    await channel._handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 1,
            "group_id": 42,
            "user_id": 100,
            "sender": {"nickname": "alice"},
            "message": [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        }
    )

    msg = await channel.bus.consume_inbound()
    assert msg.content == "alice: hello"


@pytest.mark.asyncio
async def test_send_group_media_uses_image_segment(tmp_path: Path) -> None:
    media_path = tmp_path / "a.jpg"
    media_path.write_bytes(b"jpg")

    channel = NapCatChannel(NapCatConfig(allow_from=["*"]), MessageBus())
    channel._ws = _FakeWs()

    calls: list[tuple[str, dict]] = []

    async def fake_call_api(action, params=None):
        calls.append((action, params or {}))
        return {"message_id": 1, "action": action, "params": params}

    channel._call_api = fake_call_api  # type: ignore[method-assign]

    await channel.send(
        OutboundMessage(
            channel="napcat",
            chat_id="42",
            content="hello",
            media=[str(media_path)],
            metadata={"is_group": True},
        )
    )

    assert calls[0] == ("send_group_msg", {"group_id": 42, "message": "hello"})
    assert calls[1][0] == "send_group_msg"
    assert calls[1][1]["group_id"] == 42
    assert calls[1][1]["message"][0]["type"] == "image"
    assert calls[1][1]["message"][0]["data"]["file"].startswith("file://")


@pytest.mark.asyncio
async def test_notice_and_request_handlers_log_without_bus_messages() -> None:
    channel = NapCatChannel(
        NapCatConfig(allow_from=["*"], handle_notice_events=True, handle_request_events=True),
        MessageBus(),
    )

    await channel._handle_ws_message('{"post_type":"notice","notice_type":"group_increase","group_id":1,"user_id":2}')
    await channel._handle_ws_message('{"post_type":"request","request_type":"friend","user_id":2,"comment":"hi"}')

    assert channel.bus.inbound_size == 0
