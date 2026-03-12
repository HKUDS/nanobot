import asyncio
from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
import nanobot.channels.dingtalk as dingtalk_module
from nanobot.channels.dingtalk import DingTalkChannel, NanobotDingTalkHandler
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


@pytest.mark.asyncio
async def test_handler_uses_voice_recognition_text_when_text_is_empty(monkeypatch) -> None:
    bus = MessageBus()
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["user1"]),
        bus,
    )
    handler = NanobotDingTalkHandler(channel)

    class _FakeChatbotMessage:
        text = None
        extensions = {"content": {"recognition": "voice transcript"}}
        sender_staff_id = "user1"
        sender_id = "fallback-user"
        sender_nick = "Alice"
        message_type = "audio"

        @staticmethod
        def from_dict(_data):
            return _FakeChatbotMessage()

    monkeypatch.setattr(dingtalk_module, "ChatbotMessage", _FakeChatbotMessage)
    monkeypatch.setattr(dingtalk_module, "AckMessage", SimpleNamespace(STATUS_OK="OK"))

    status, body = await handler.process(
        SimpleNamespace(
            data={
                "conversationType": "2",
                "conversationId": "conv123",
                "text": {"content": ""},
            }
        )
    )

    await asyncio.gather(*list(channel._background_tasks))
    msg = await bus.consume_inbound()

    assert (status, body) == ("OK", "OK")
    assert msg.content == "voice transcript"
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group:conv123"
