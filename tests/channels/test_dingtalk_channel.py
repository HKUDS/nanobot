import asyncio
from types import SimpleNamespace

import pytest

# Check optional dingtalk dependencies before running tests
try:
    from nanobot.channels import dingtalk
    DINGTALK_AVAILABLE = getattr(dingtalk, "DINGTALK_AVAILABLE", False)
except ImportError:
    DINGTALK_AVAILABLE = False

if not DINGTALK_AVAILABLE:
    pytest.skip("DingTalk dependencies not installed (dingtalk-stream)", allow_module_level=True)

from nanobot.bus.queue import MessageBus
import nanobot.channels.dingtalk as dingtalk_module
from nanobot.channels.dingtalk import DingTalkChannel, NanobotDingTalkHandler
from nanobot.channels.dingtalk import DingTalkConfig


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = "{}"
        self.content = b""
        self.headers = {"content-type": "application/json"}

    def json(self) -> dict:
        return self._json_body


class _FakeHttp:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses) if responses else []

    def _next_response(self) -> _FakeResponse:
        if self._responses:
            return self._responses.pop(0)
        return _FakeResponse()

    async def post(self, url: str, json=None, headers=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._next_response()

    async def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url})
        return self._next_response()


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


@pytest.mark.asyncio
async def test_handler_processes_file_message(monkeypatch) -> None:
    """Test that file messages are handled and forwarded with downloaded path."""
    bus = MessageBus()
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["user1"]),
        bus,
    )
    handler = NanobotDingTalkHandler(channel)

    class _FakeFileChatbotMessage:
        text = None
        extensions = {}
        image_content = None
        rich_text_content = None
        sender_staff_id = "user1"
        sender_id = "fallback-user"
        sender_nick = "Alice"
        message_type = "file"

        @staticmethod
        def from_dict(_data):
            return _FakeFileChatbotMessage()

    async def fake_download(download_code, filename, sender_id):
        return f"/tmp/nanobot_dingtalk/{sender_id}/{filename}"

    monkeypatch.setattr(dingtalk_module, "ChatbotMessage", _FakeFileChatbotMessage)
    monkeypatch.setattr(dingtalk_module, "AckMessage", SimpleNamespace(STATUS_OK="OK"))
    monkeypatch.setattr(channel, "_download_dingtalk_file", fake_download)

    status, body = await handler.process(
        SimpleNamespace(
            data={
                "conversationType": "1",
                "content": {"downloadCode": "abc123", "fileName": "report.xlsx"},
                "text": {"content": ""},
            }
        )
    )

    await asyncio.gather(*list(channel._background_tasks))
    msg = await bus.consume_inbound()

    assert (status, body) == ("OK", "OK")
    assert "[File]" in msg.content
    assert "/tmp/nanobot_dingtalk/user1/report.xlsx" in msg.content


@pytest.mark.asyncio
async def test_download_dingtalk_file(tmp_path, monkeypatch) -> None:
    """Test the two-step file download flow (get URL then download content)."""
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"]),
        MessageBus(),
    )

    # Mock access token
    async def fake_get_token():
        return "test-token"

    monkeypatch.setattr(channel, "_get_access_token", fake_get_token)

    # Mock HTTP: first POST returns downloadUrl, then GET returns file bytes
    file_content = b"fake file content"
    channel._http = _FakeHttp(responses=[
        _FakeResponse(200, {"downloadUrl": "https://example.com/tmpfile"}),
        _FakeResponse(200),
    ])
    channel._http._responses[1].content = file_content

    # Redirect media dir to tmp_path
    monkeypatch.setattr(
        "nanobot.config.paths.get_media_dir",
        lambda channel_name=None: tmp_path / channel_name if channel_name else tmp_path,
    )

    result = await channel._download_dingtalk_file("code123", "test.xlsx", "user1")

    assert result is not None
    assert result.endswith("test.xlsx")
    assert (tmp_path / "dingtalk" / "user1" / "test.xlsx").read_bytes() == file_content

    # Verify API calls
    assert channel._http.calls[0]["method"] == "POST"
    assert "messageFiles/download" in channel._http.calls[0]["url"]
    assert channel._http.calls[0]["json"]["downloadCode"] == "code123"
    assert channel._http.calls[1]["method"] == "GET"
