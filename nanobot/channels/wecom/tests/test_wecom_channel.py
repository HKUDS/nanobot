"""Tests for WeCom channel: helpers, download, upload, send, and message processing."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    import importlib.util

    WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None
except ImportError:
    WECOM_AVAILABLE = False

if not WECOM_AVAILABLE:
    pytest.skip("WeCom dependencies not installed (wecom_aibot_sdk)", allow_module_level=True)

from wecom_aibot_sdk import UploadResult, WSClient

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.wecom.runtime import (
    WecomChannel,
    WecomConfig,
    _sanitize_filename,
)


class _FakeFrame:
    """Minimal frame object with a body dict."""

    def __init__(self, body: dict | None = None):
        self.body = body or {}


class _FakeWeComClient:
    """Fake WeCom client with mock methods."""

    def __init__(self):
        self.download_file = AsyncMock(return_value=(None, None))
        self.upload_media = AsyncMock(
            return_value=UploadResult(media_id="media_123", media_type="image")
        )
        self.reply = AsyncMock()
        self.reply_stream = AsyncMock()
        self.send_message = AsyncMock()
        self.reply_welcome = AsyncMock()


# ── SDK contract and helper function tests ─────────────────────────


def test_sdk_exposes_media_upload_api() -> None:
    """The declared SDK version provides the public API used by this channel."""
    assert callable(WSClient.upload_media)


def test_sanitize_filename_strips_path_traversal() -> None:
    assert _sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_keeps_chinese_chars() -> None:
    assert _sanitize_filename("文件（1）.jpg") == "文件（1）.jpg"


def test_sanitize_filename_empty_input() -> None:
    assert _sanitize_filename("") == "unnamed"


def test_sanitize_filename_empty_or_dots_fallback() -> None:
    assert _sanitize_filename("...") == "unnamed"
    assert _sanitize_filename("..", fallback="fallback.txt") == "fallback.txt"
    assert _sanitize_filename("...", fallback="../../outside.txt") == "outside.txt"
    assert _sanitize_filename("") == "unnamed"


# ── _download_and_save_media() ──────────────────────────────────────


@pytest.mark.asyncio
async def test_download_and_save_success() -> None:
    """Successful download writes file and returns sanitized path."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    fake_data = b"\x89PNG\r\nfake image"
    client.download_file.return_value = (fake_data, "raw_photo.png")

    with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(tempfile.gettempdir())):
        path = await channel._download_and_save_media("https://example.com/img.png", "aes_key", "image", "photo.png")

    assert path is not None
    assert os.path.isfile(path)
    assert os.path.basename(path) == "photo.png"
    # Cleanup
    os.unlink(path)


@pytest.mark.asyncio
async def test_download_and_save_sanitizes_sdk_fallback(tmp_path: Path) -> None:
    """An unsafe SDK filename cannot escape the channel media directory."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    client.download_file.return_value = (b"payload", "../../outside.txt")
    channel._client = client

    with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=tmp_path):
        path = await channel._download_and_save_media(
            "https://example.com/file",
            "aes_key",
            "file",
            "...",
        )

    assert path is not None
    assert Path(path) == tmp_path / "outside.txt"
    assert Path(path).read_bytes() == b"payload"


@pytest.mark.asyncio
async def test_download_and_save_oversized_rejected() -> None:
    """Data exceeding 200MB is rejected → returns None."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    big_data = b"\x00" * (200 * 1024 * 1024 + 1)  # 200MB + 1 byte
    client.download_file.return_value = (big_data, "big.bin")

    with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(tempfile.gettempdir())):
        result = await channel._download_and_save_media("https://example.com/big.bin", "key", "file", "big.bin")

    assert result is None


@pytest.mark.asyncio
async def test_download_and_save_failure() -> None:
    """SDK returns None data → returns None."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    client.download_file.return_value = (None, None)

    with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(tempfile.gettempdir())):
        result = await channel._download_and_save_media("https://example.com/fail.png", "key", "image")

    assert result is None


# ── send() ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_text_with_frame() -> None:
    """When frame is stored, send uses reply_stream for final text."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel._generate_req_id = lambda x: f"req_{x}"
    channel._chat_frames["chat1"] = _FakeFrame()

    await channel.send(
        OutboundMessage(channel="wecom", chat_id="chat1", content="hello")
    )

    client.reply_stream.assert_called_once()
    call_args = client.reply_stream.call_args
    assert call_args[0][2] == "hello"  # content arg


@pytest.mark.asyncio
async def test_send_progress_with_frame() -> None:
    """Progress events use reply_stream with finish=False."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel._generate_req_id = lambda x: f"req_{x}"
    channel._chat_frames["chat1"] = _FakeFrame()

    await channel.send(
        OutboundMessage(
            channel="wecom",
            chat_id="chat1",
            content="thinking...",
            event=ProgressEvent(content="thinking..."),
        )
    )

    client.reply_stream.assert_called_once()
    call_args = client.reply_stream.call_args
    assert call_args[0][2] == "thinking..."  # content arg
    assert call_args[1]["finish"] is False


@pytest.mark.asyncio
async def test_send_proactive_without_frame() -> None:
    """Without stored frame, send uses send_message with markdown."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    await channel.send(
        OutboundMessage(channel="wecom", chat_id="chat1", content="proactive msg")
    )

    client.send_message.assert_called_once()
    call_args = client.send_message.call_args
    assert call_args[0][0] == "chat1"
    assert call_args[0][1]["msgtype"] == "markdown"


@pytest.mark.asyncio
async def test_send_media_then_text() -> None:
    """Media files are uploaded and sent before text content."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        tmp = f.name

    try:
        channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
        client = _FakeWeComClient()
        channel._client = client
        channel._generate_req_id = lambda x: f"req_{x}"
        frame = _FakeFrame()
        channel._chat_frames["chat1"] = frame

        await channel.send(
            OutboundMessage(channel="wecom", chat_id="chat1", content="see image", media=[tmp])
        )

        client.upload_media.assert_awaited_once_with(tmp)
        client.reply.assert_awaited_once_with(
            frame,
            {"msgtype": "image", "image": {"media_id": "media_123"}},
        )

        # Text should have been sent via reply_stream
        client.reply_stream.assert_called_once()
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_send_proactive_media_uses_uploaded_media_id() -> None:
    """Proactive media uses the SDK upload result before sending text."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4")
        tmp = f.name

    try:
        channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
        client = _FakeWeComClient()
        client.upload_media.return_value = UploadResult(media_id="media_file", media_type="file")
        channel._client = client

        await channel.send(
            OutboundMessage(channel="wecom", chat_id="chat1", content="see file", media=[tmp])
        )

        client.upload_media.assert_awaited_once_with(tmp)
        assert client.send_message.await_args_list[0].args == (
            "chat1",
            {"msgtype": "file", "file": {"media_id": "media_file"}},
        )
        assert client.send_message.await_args_list[1].args == (
            "chat1",
            {"msgtype": "markdown", "markdown": {"content": "see file"}},
        )
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_send_media_upload_failure_falls_back_to_text() -> None:
    """Upload failures become a visible text marker without losing the reply."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name

    try:
        channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
        client = _FakeWeComClient()
        client.upload_media.side_effect = RuntimeError("upload failed")
        channel._client = client
        channel._generate_req_id = lambda x: f"req_{x}"
        channel._chat_frames["chat1"] = _FakeFrame()

        await channel.send(
            OutboundMessage(channel="wecom", chat_id="chat1", content="see image", media=[tmp])
        )

        assert "[file upload failed:" in client.reply_stream.await_args.args[2]
        assert "see image" in client.reply_stream.await_args.args[2]
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_send_media_delivery_failure_propagates_for_manager_retry() -> None:
    """A failed media reply still propagates after a successful upload."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name

    try:
        channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
        client = _FakeWeComClient()
        client.reply.side_effect = RuntimeError("media send failed")
        channel._client = client
        channel._chat_frames["chat1"] = _FakeFrame()

        with pytest.raises(RuntimeError, match="media send failed"):
            await channel.send(
                OutboundMessage(channel="wecom", chat_id="chat1", content="", media=[tmp])
            )
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_send_media_file_not_found() -> None:
    """Non-existent media path is skipped with a warning."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel._generate_req_id = lambda x: f"req_{x}"
    channel._chat_frames["chat1"] = _FakeFrame()

    await channel.send(
        OutboundMessage(channel="wecom", chat_id="chat1", content="hello", media=["/nonexistent/file.png"])
    )

    # reply_stream should still be called for the text part
    client.reply_stream.assert_called_once()
    # No media reply should happen
    media_calls = [c for c in client.reply.call_args_list if c[0][1].get("msgtype") in ("image", "file", "video")]
    assert len(media_calls) == 0


@pytest.mark.asyncio
async def test_send_exception_propagates_for_manager_retry() -> None:
    """Delivery failures must propagate to the channel manager."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["*"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel._generate_req_id = lambda x: f"req_{x}"
    channel._chat_frames["chat1"] = _FakeFrame()

    # Make reply_stream raise
    client.reply_stream.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await channel.send(
            OutboundMessage(channel="wecom", chat_id="chat1", content="fail test")
        )
    client.reply_stream.assert_called_once()


# ── _process_message() ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_text_message() -> None:
    """Text message is routed to bus with correct fields."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    frame = _FakeFrame(body={
        "msgid": "msg_text_1",
        "chatid": "chat1",
        "chattype": "single",
        "from": {"userid": "user1"},
        "text": {"content": "hello wecom"},
    })

    await channel._process_message(frame, "text")

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "chat1"
    assert msg.content == "hello wecom"
    assert msg.metadata["msg_type"] == "text"


@pytest.mark.asyncio
async def test_enter_chat_ignores_unauthorized_user_before_welcome() -> None:
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["allowed"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel.config.welcome_message = "hello"

    await channel._on_enter_chat(_FakeFrame(body={"chatid": "blocked"}))

    client.reply_welcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_ignores_unauthorized_sender_before_download() -> None:
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["allowed"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client
    channel._handle_message = AsyncMock()

    frame = _FakeFrame(body={
        "msgid": "msg_blocked",
        "chatid": "chat1",
        "from": {"userid": "blocked"},
        "image": {"url": "https://example.com/img.png", "aeskey": "key123"},
    })

    await channel._process_message(frame, "image")

    client.download_file.assert_not_awaited()
    channel._handle_message.assert_not_awaited()
    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_process_image_message() -> None:
    """Image message: download success → media_paths non-empty."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        saved = f.name

    client.download_file.return_value = (b"\x89PNG\r\n", "photo.png")
    channel._client = client

    try:
        with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(os.path.dirname(saved))):
            frame = _FakeFrame(body={
                "msgid": "msg_img_1",
                "chatid": "chat1",
                "from": {"userid": "user1"},
                "image": {"url": "https://example.com/img.png", "aeskey": "key123"},
            })
            await channel._process_message(frame, "image")

        msg = await channel.bus.consume_inbound()
        assert len(msg.media) == 1
        assert msg.media[0].endswith("photo.png")
        assert "[image:" in msg.content
    finally:
        if os.path.exists(saved):
            pass  # may have been overwritten; clean up if exists
        # Clean up any photo.png in tempdir
        p = os.path.join(os.path.dirname(saved), "photo.png")
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_process_file_message() -> None:
    """File message: download success → media_paths non-empty (critical fix verification)."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake")
        saved = f.name

    client.download_file.return_value = (b"%PDF-1.4 fake", "report.pdf")
    channel._client = client

    try:
        with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(os.path.dirname(saved))):
            frame = _FakeFrame(body={
                "msgid": "msg_file_1",
                "chatid": "chat1",
                "from": {"userid": "user1"},
                "file": {"url": "https://example.com/report.pdf", "aeskey": "key456", "name": "report.pdf"},
            })
            await channel._process_message(frame, "file")

        msg = await channel.bus.consume_inbound()
        assert len(msg.media) == 1
        assert msg.media[0].endswith("report.pdf")
        assert "[file: report.pdf]" in msg.content
    finally:
        p = os.path.join(os.path.dirname(saved), "report.pdf")
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_process_file_message_uses_sdk_filename_when_name_missing(tmp_path: Path) -> None:
    """Without `file.name`, fall back to SDK fname instead of saving as 'unknown' (#3737)."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()
    client.download_file.return_value = (b"%PDF-1.4 fake", "real_name.pdf")
    channel._client = client

    with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=tmp_path):
        frame = _FakeFrame(body={
            "msgid": "msg_file_2", "chatid": "chat1", "from": {"userid": "user1"},
            "file": {"url": "https://example.com/x", "aeskey": "key456"},
        })
        await channel._process_message(frame, "file")

    msg = await channel.bus.consume_inbound()
    assert msg.media == [str(tmp_path / "real_name.pdf")]
    assert "[file: real_name.pdf]" in msg.content


@pytest.mark.asyncio
async def test_process_voice_message() -> None:
    """Voice message: transcribed text is included in content."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    frame = _FakeFrame(body={
        "msgid": "msg_voice_1",
        "chatid": "chat1",
        "from": {"userid": "user1"},
        "voice": {"content": "transcribed text here"},
    })

    await channel._process_message(frame, "voice")

    msg = await channel.bus.consume_inbound()
    assert "transcribed text here" in msg.content
    assert "[voice]" in msg.content


@pytest.mark.asyncio
async def test_process_mixed_message() -> None:
    """Mixed message: contains picture and text message types."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        saved = f.name

    client.download_file.return_value = (b"\x89PNG\r\n", "photo.png")
    channel._client = client

    try:
        with patch("nanobot.channels.wecom.runtime.get_media_dir", return_value=Path(os.path.dirname(saved))):
            frame = _FakeFrame(body={
                "msgid": "msg_mixed_1",
                "chatid": "chat1",
                "msgtype": "mixed",
                "from": {"userid": "user1"},
                "mixed": {
                    "msg_item": [
                        {"msgtype": "text", "text": {"content": "hello wecom"}},
                        {"msgtype": "image", "image": {"url": "https://example.com/img.png", "aeskey": "key123"}}
                    ]
                }
            })
            await channel._process_message(frame, "mixed")

        msg = await channel.bus.consume_inbound()
        assert msg.sender_id == "user1"
        assert msg.chat_id == "chat1"
        assert msg.content.startswith("hello wecom")
        assert msg.metadata["msg_type"] == "mixed"
        assert len(msg.media) == 1
        assert msg.media[0].endswith("photo.png")
        assert "[image:" in msg.content
    finally:
        # Clean up any photo.png in tempdir
        p = os.path.join(os.path.dirname(saved), "photo.png")
        if os.path.exists(p):
            os.unlink(p)


@pytest.mark.asyncio
async def test_process_message_deduplication() -> None:
    """Same msg_id is not processed twice."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    frame = _FakeFrame(body={
        "msgid": "msg_dup_1",
        "chatid": "chat1",
        "from": {"userid": "user1"},
        "text": {"content": "once"},
    })

    await channel._process_message(frame, "text")
    await channel._process_message(frame, "text")

    msg = await channel.bus.consume_inbound()
    assert msg.content == "once"

    # Second message should not appear on the bus
    assert channel.bus.inbound.empty()


@pytest.mark.asyncio
async def test_process_message_empty_content_skipped() -> None:
    """Message with empty content produces no bus message."""
    channel = WecomChannel(WecomConfig(bot_id="b", secret="s", allow_from=["user1"]), MessageBus())
    client = _FakeWeComClient()
    channel._client = client

    frame = _FakeFrame(body={
        "msgid": "msg_empty_1",
        "chatid": "chat1",
        "from": {"userid": "user1"},
        "text": {"content": ""},
    })

    await channel._process_message(frame, "text")

    assert channel.bus.inbound.empty()
