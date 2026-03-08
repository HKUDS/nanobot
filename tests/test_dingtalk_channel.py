from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.dingtalk import DingTalkChannel
from nanobot.config.schema import DingTalkConfig


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = "{}"

    def json(self) -> dict:
        return self._json_body


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_group_message_keeps_sender_id_and_routes_chat_id() -> None:
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["user1"])
    bus = MessageBus()
    channel = DingTalkChannel(config, bus)

    await channel._on_message(
        "hello",
        sender_id="user1",
        sender_name="Alice",
        conversation_type="2",
        conversation_id="conv123",
    )

    msg = await bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group:conv123"
    assert msg.metadata["conversation_type"] == "2"


@pytest.mark.asyncio
async def test_group_send_uses_group_messages_api() -> None:
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())
    channel._http = _FakeHttp()

    ok = await channel._send_batch_message(
        "token",
        "group:conv123",
        "sampleMarkdown",
        {"text": "hello", "title": "Nanobot Reply"},
    )

    assert ok is True
    call = channel._http.calls[0]
    assert call["url"] == "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
    assert call["json"]["openConversationId"] == "conv123"
    assert call["json"]["msgKey"] == "sampleMarkdown"
