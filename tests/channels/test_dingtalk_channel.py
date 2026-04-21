import asyncio
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
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


class _NetworkErrorHttp:
    """HTTP client stub that raises httpx.TransportError on every request."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, json=None, headers=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        raise httpx.ConnectError("Connection refused")

    async def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url})
        raise httpx.ConnectError("Connection refused")


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


def test_normalize_upload_payload_zips_html_attachment() -> None:
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"]),
        MessageBus(),
    )

    data, filename, content_type = channel._normalize_upload_payload(
        "report.html",
        b"<html><body>Hello</body></html>",
        "text/html",
    )

    assert filename == "report.zip"
    assert content_type == "application/zip"

    archive = zipfile.ZipFile(BytesIO(data))
    assert archive.namelist() == ["report.html"]
    assert archive.read("report.html") == b"<html><body>Hello</body></html>"


@pytest.mark.asyncio
async def test_send_media_ref_zips_html_before_upload(tmp_path, monkeypatch) -> None:
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"]),
        MessageBus(),
    )

    html_path = tmp_path / "report.html"
    html_path.write_text("<html><body>Hello</body></html>", encoding="utf-8")

    captured: dict[str, object] = {}

    async def fake_upload_media(*, token, data, media_type, filename, content_type):
        captured.update(
            {
                "token": token,
                "data": data,
                "media_type": media_type,
                "filename": filename,
                "content_type": content_type,
            }
        )
        return "media-123"

    async def fake_send_batch_message(token, chat_id, msg_key, msg_param):
        captured.update(
            {
                "sent_token": token,
                "chat_id": chat_id,
                "msg_key": msg_key,
                "msg_param": msg_param,
            }
        )
        return True

    monkeypatch.setattr(channel, "_upload_media", fake_upload_media)
    monkeypatch.setattr(channel, "_send_batch_message", fake_send_batch_message)

    ok = await channel._send_media_ref("token-123", "user-1", str(html_path))

    assert ok is True
    assert captured["media_type"] == "file"
    assert captured["filename"] == "report.zip"
    assert captured["content_type"] == "application/zip"
    assert captured["msg_key"] == "sampleFile"
    assert captured["msg_param"] == {
        "mediaId": "media-123",
        "fileName": "report.zip",
        "fileType": "zip",
    }

    archive = zipfile.ZipFile(BytesIO(captured["data"]))
    assert archive.namelist() == ["report.html"]


# ── Exception handling tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_batch_message_propagates_transport_error() -> None:
    """Network/transport errors must re-raise so callers can retry."""
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())
    channel._http = _NetworkErrorHttp()

    with pytest.raises(httpx.ConnectError, match="Connection refused"):
        await channel._send_batch_message(
            "token",
            "user123",
            "sampleMarkdown",
            {"text": "hello", "title": "Nanobot Reply"},
        )

    # The POST was attempted exactly once
    assert len(channel._http.calls) == 1
    assert channel._http.calls[0]["method"] == "POST"


@pytest.mark.asyncio
async def test_send_batch_message_returns_false_on_api_error() -> None:
    """DingTalk API-level errors (non-200 status, errcode != 0) should return False."""
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())

    # Non-200 status code → API error → return False
    channel._http = _FakeHttp(responses=[_FakeResponse(400, {"errcode": 400})])
    result = await channel._send_batch_message(
        "token", "user123", "sampleMarkdown", {"text": "hello"}
    )
    assert result is False

    # 200 with non-zero errcode → API error → return False
    channel._http = _FakeHttp(responses=[_FakeResponse(200, {"errcode": 100})])
    result = await channel._send_batch_message(
        "token", "user123", "sampleMarkdown", {"text": "hello"}
    )
    assert result is False

    # 200 with errcode=0 → success → return True
    channel._http = _FakeHttp(responses=[_FakeResponse(200, {"errcode": 0})])
    result = await channel._send_batch_message(
        "token", "user123", "sampleMarkdown", {"text": "hello"}
    )
    assert result is True


@pytest.mark.asyncio
async def test_send_media_ref_short_circuits_on_transport_error() -> None:
    """When the first send fails with a transport error, _send_media_ref must
    re-raise immediately instead of trying download+upload+fallback."""
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())
    channel._http = _NetworkErrorHttp()

    # An image URL triggers the sampleImageMsg path first
    with pytest.raises(httpx.ConnectError, match="Connection refused"):
        await channel._send_media_ref("token", "user123", "https://example.com/photo.jpg")

    # Only one POST should have been attempted — no download/upload/fallback
    assert len(channel._http.calls) == 1
    assert channel._http.calls[0]["method"] == "POST"


@pytest.mark.asyncio
async def test_send_media_ref_short_circuits_on_download_transport_error() -> None:
    """When the image URL send returns an API error (False) but the download
    for the fallback hits a transport error, it must re-raise rather than
    silently returning False."""
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())

    # First POST (sampleImageMsg) returns API error → False, then GET (download) raises transport error
    class _MixedHttp:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def post(self, url, json=None, headers=None, **kwargs):
            self.calls.append({"method": "POST", "url": url})
            # API-level failure: 200 with errcode != 0
            return _FakeResponse(200, {"errcode": 100})

        async def get(self, url, **kwargs):
            self.calls.append({"method": "GET", "url": url})
            raise httpx.ConnectError("Connection refused")

    channel._http = _MixedHttp()

    with pytest.raises(httpx.ConnectError, match="Connection refused"):
        await channel._send_media_ref("token", "user123", "https://example.com/photo.jpg")

    # Should have attempted POST (image URL) and GET (download), but NOT upload
    assert len(channel._http.calls) == 2
    assert channel._http.calls[0]["method"] == "POST"
    assert channel._http.calls[1]["method"] == "GET"


@pytest.mark.asyncio
async def test_send_media_ref_short_circuits_on_upload_transport_error() -> None:
    """When download succeeds but upload hits a transport error, must re-raise."""
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())

    image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal JPEG-ish data

    class _UploadFailsHttp:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def post(self, url, json=None, headers=None, files=None, **kwargs):
            self.calls.append({"method": "POST", "url": url})
            # If it's the upload endpoint, raise transport error
            if "media/upload" in url:
                raise httpx.ConnectError("Connection refused")
            # Otherwise (sampleImageMsg), return API error to trigger fallback
            return _FakeResponse(200, {"errcode": 100})

        async def get(self, url, **kwargs):
            self.calls.append({"method": "GET", "url": url})
            resp = _FakeResponse(200)
            resp.content = image_bytes
            resp.headers = {"content-type": "image/jpeg"}
            return resp

    channel._http = _UploadFailsHttp()

    with pytest.raises(httpx.ConnectError, match="Connection refused"):
        await channel._send_media_ref("token", "user123", "https://example.com/photo.jpg")

    # POST (image URL), GET (download), POST (upload) attempted — no further sends
    methods = [c["method"] for c in channel._http.calls]
    assert methods == ["POST", "GET", "POST"]
