"""Tests for QQ channel media support: helpers, send, inbound, and upload."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from nanobot.channels import qq

    QQ_AVAILABLE = getattr(qq, "QQ_AVAILABLE", False)
except ImportError:
    QQ_AVAILABLE = False

if not QQ_AVAILABLE:
    pytest.skip("QQ dependencies not installed (qq-botpy)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import (
    QQ_FILE_TYPE_FILE,
    QQ_FILE_TYPE_IMAGE,
    QQChannel,
    QQConfig,
    _guess_send_file_type,
    _is_image_name,
    _sanitize_filename,
)


class _FakeApi:
    def __init__(self) -> None:
        self.c2c_calls: list[dict] = []
        self.group_calls: list[dict] = []

    async def post_c2c_message(self, **kwargs) -> None:
        self.c2c_calls.append(kwargs)

    async def post_group_message(self, **kwargs) -> None:
        self.group_calls.append(kwargs)


class _FakeHttp:
    """Fake _http for _post_base64file tests."""

    def __init__(self, return_value: dict | None = None) -> None:
        self.return_value = return_value or {}
        self.calls: list[tuple] = []

    async def request(self, route, **kwargs):
        self.calls.append((route, kwargs))
        return self.return_value


class _FakeClient:
    def __init__(self, http_return: dict | None = None) -> None:
        self.api = _FakeApi()
        self.api._http = _FakeHttp(http_return)


# ── Helper function tests (pure, no async) ──────────────────────────


def test_sanitize_filename_strips_path_traversal() -> None:
    assert _sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_keeps_chinese_chars() -> None:
    assert _sanitize_filename("文件（1）.jpg") == "文件（1）.jpg"


def test_sanitize_filename_strips_unsafe_chars() -> None:
    result = _sanitize_filename('file<>:"|?*.txt')
    # All unsafe chars replaced with "_", but * is replaced too
    assert result.startswith("file")
    assert result.endswith(".txt")
    assert "<" not in result
    assert ">" not in result
    assert '"' not in result
    assert "|" not in result
    assert "?" not in result


def test_sanitize_filename_empty_input() -> None:
    assert _sanitize_filename("") == ""


def test_is_image_name_with_known_extensions() -> None:
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".svg"):
        assert _is_image_name(f"photo{ext}") is True


def test_is_image_name_with_unknown_extension() -> None:
    for ext in (".pdf", ".txt", ".mp3", ".mp4"):
        assert _is_image_name(f"doc{ext}") is False


def test_guess_send_file_type_image() -> None:
    assert _guess_send_file_type("photo.png") == QQ_FILE_TYPE_IMAGE
    assert _guess_send_file_type("pic.jpg") == QQ_FILE_TYPE_IMAGE


def test_guess_send_file_type_file() -> None:
    assert _guess_send_file_type("doc.pdf") == QQ_FILE_TYPE_FILE


def test_guess_send_file_type_by_mime() -> None:
    # A filename with no known extension but whose mime type is image/*
    assert _guess_send_file_type("photo.xyz_image_test") == QQ_FILE_TYPE_FILE


# ── send() exception handling ───────────────────────────────────────


@pytest.mark.asyncio
async def test_send_exception_caught_not_raised() -> None:
    """Exceptions inside send() must not propagate."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    with patch.object(channel, "_send_text_only", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        await channel.send(
            OutboundMessage(channel="qq", chat_id="user1", content="hello")
        )
    # No exception raised — test passes if we get here.


@pytest.mark.asyncio
async def test_send_media_then_text() -> None:
    """Media is sent before text when both are present."""
    import tempfile

    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        tmp = f.name

    try:
        with patch.object(channel, "_post_base64file", new_callable=AsyncMock, return_value={"file_info": "1"}) as mock_upload:
            await channel.send(
                OutboundMessage(
                    channel="qq",
                    chat_id="user1",
                    content="text after image",
                    media=[tmp],
                    metadata={"message_id": "m1"},
                )
            )
            assert mock_upload.called

        # Text should have been sent via c2c (default chat type)
        text_calls = [c for c in channel._client.api.c2c_calls if c.get("msg_type") == 0]
        assert len(text_calls) >= 1
        assert text_calls[-1]["content"] == "text after image"
    finally:
        import os
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_send_media_failure_falls_back_to_text() -> None:
    """When _send_media returns False, a failure notice is appended."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    with patch.object(channel, "_send_media", new_callable=AsyncMock, return_value=False):
        await channel.send(
            OutboundMessage(
                channel="qq",
                chat_id="user1",
                content="hello",
                media=["https://example.com/bad.png"],
                metadata={"message_id": "m1"},
            )
        )

    # Should have the failure text among the c2c calls
    failure_calls = [c for c in channel._client.api.c2c_calls if "Attachment send failed" in c.get("content", "")]
    assert len(failure_calls) == 1
    assert "bad.png" in failure_calls[0]["content"]


# ── _on_message() exception handling ────────────────────────────────


@pytest.mark.asyncio
async def test_on_message_exception_caught_not_raised() -> None:
    """Missing required attributes should not crash _on_message."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    # Construct a message-like object that lacks 'author' — triggers AttributeError
    bad_data = SimpleNamespace(id="x1", content="hi")
    # Should not raise
    await channel._on_message(bad_data, is_group=False)


@pytest.mark.asyncio
async def test_on_message_with_attachments() -> None:
    """Messages with attachments produce media_paths and formatted content."""
    import tempfile

    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        saved_path = f.name

    att = SimpleNamespace(url="", filename="screenshot.png", content_type="image/png")

    # Patch _download_to_media_dir_chunked to return the temp file path
    async def fake_download(url, filename_hint=""):
        return saved_path

    try:
        with patch.object(channel, "_download_to_media_dir_chunked", side_effect=fake_download):
            data = SimpleNamespace(
                id="att1",
                content="look at this",
                author=SimpleNamespace(user_openid="u1"),
                attachments=[att],
            )
            await channel._on_message(data, is_group=False)

        msg = await channel.bus.consume_inbound()
        assert "look at this" in msg.content
        assert "screenshot.png" in msg.content
        assert "Received files:" in msg.content
        assert len(msg.media) == 1
        assert msg.media[0] == saved_path
    finally:
        import os
        os.unlink(saved_path)


# ── _post_base64file() ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_base64file_omits_file_name_for_images() -> None:
    """file_type=1 (image) → payload must not contain file_name."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())
    channel._client = _FakeClient(http_return={"file_info": "img_abc"})

    await channel._post_base64file(
        chat_id="user1",
        is_group=False,
        file_type=QQ_FILE_TYPE_IMAGE,
        file_data="ZmFrZQ==",
        file_name="photo.png",
    )

    http = channel._client.api._http
    assert len(http.calls) == 1
    payload = http.calls[0][1]["json"]
    assert "file_name" not in payload
    assert payload["file_type"] == QQ_FILE_TYPE_IMAGE


@pytest.mark.asyncio
async def test_post_base64file_includes_file_name_for_files() -> None:
    """file_type=4 (file) → payload must contain file_name."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())
    channel._client = _FakeClient(http_return={"file_info": "file_abc"})

    await channel._post_base64file(
        chat_id="user1",
        is_group=False,
        file_type=QQ_FILE_TYPE_FILE,
        file_data="ZmFrZQ==",
        file_name="report.pdf",
    )

    http = channel._client.api._http
    assert len(http.calls) == 1
    payload = http.calls[0][1]["json"]
    assert payload["file_name"] == "report.pdf"
    assert payload["file_type"] == QQ_FILE_TYPE_FILE


@pytest.mark.asyncio
async def test_post_base64file_filters_response_to_file_info() -> None:
    """Response with file_info + extra fields must be filtered to only file_info."""
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())
    channel._client = _FakeClient(http_return={
        "file_info": "fi_123",
        "file_uuid": "uuid_xxx",
        "ttl": 3600,
    })

    result = await channel._post_base64file(
        chat_id="user1",
        is_group=False,
        file_type=QQ_FILE_TYPE_FILE,
        file_data="ZmFrZQ==",
        file_name="doc.pdf",
    )

    assert result == {"file_info": "fi_123"}
    assert "file_uuid" not in result
    assert "ttl" not in result
