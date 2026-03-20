import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import QQChannel, QQConfig


class _FakeApi:
    def __init__(self) -> None:
        self.c2c_calls: list[dict] = []
        self.group_calls: list[dict] = []

    async def post_c2c_message(self, **kwargs) -> None:
        self.c2c_calls.append(kwargs)

    async def post_group_message(self, **kwargs) -> None:
        self.group_calls.append(kwargs)


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeApi()


@pytest.mark.asyncio
async def test_on_group_message_routes_to_group_chat_id() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())

    data = SimpleNamespace(
        id="msg1",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=True)

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_on_c2c_audio_attachment_uses_transcription_when_text_is_empty(monkeypatch) -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())

    async def fake_download(_url: str, filename_hint: str = "") -> str:
        assert filename_hint == "voice.amr"
        return "/tmp/nanobot/qq/audio.amr"

    async def fake_prepare(path: str) -> str:
        return path

    async def fake_transcribe(_path: str) -> str:
        return "voice transcript"

    monkeypatch.setattr(channel, "_download_to_media_dir_chunked", fake_download)
    monkeypatch.setattr(channel, "_prepare_audio_for_transcription", fake_prepare)
    monkeypatch.setattr(channel, "transcribe_audio", fake_transcribe)

    data = SimpleNamespace(
        id="msg-audio",
        content="",
        attachments=[
            SimpleNamespace(
                url="https://example.com/voice.amr",
                filename="voice.amr",
                content_type="audio/amr",
            )
        ],
        author=SimpleNamespace(user_openid="user123"),
    )

    await channel._on_message(data, is_group=False)

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user123"
    assert msg.chat_id == "user123"
    assert "[transcription: voice transcript]" in msg.content
    assert "Received files:" in msg.content
    assert msg.media == ["/tmp/nanobot/qq/audio.amr"]
    assert msg.metadata["attachments"][0]["type"] == "audio"
    assert msg.metadata["attachments"][0]["saved_path"] == "/tmp/nanobot/qq/audio.amr"


@pytest.mark.asyncio
async def test_prepare_audio_for_transcription_decodes_silk_header(monkeypatch, tmp_path) -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    silk_path = tmp_path / "voice.amr"
    silk_path.write_bytes(b"\x02#!SILK_V3payload")

    calls: list[tuple[str, str]] = []

    def fake_silk_to_wav(src: str, dst: str) -> None:
        calls.append((src, dst))
        Path(dst).write_bytes(b"RIFF")

    monkeypatch.setattr("nanobot.channels.qq.PILK_AVAILABLE", True)
    monkeypatch.setattr("nanobot.channels.qq.pilk.silk_to_wav", fake_silk_to_wav)

    prepared = await channel._prepare_audio_for_transcription(str(silk_path))

    assert prepared.endswith(".wav")
    assert Path(prepared).exists()
    assert calls == [(str(silk_path), prepared)]


@pytest.mark.asyncio
async def test_send_group_message_uses_plain_text_group_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.c2c_calls


@pytest.mark.asyncio
async def test_send_c2c_message_uses_plain_text_c2c_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.c2c_calls) == 1
    call = channel._client.api.c2c_calls[0]
    assert call == {
        "openid": "user123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.group_calls


@pytest.mark.asyncio
async def test_send_group_message_uses_markdown_when_configured() -> None:
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["*"], msg_format="markdown"),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="**hello**",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 2,
        "markdown": {"content": "**hello**"},
        "msg_id": "msg1",
        "msg_seq": 2,
    }


@pytest.mark.asyncio
async def test_read_media_bytes_local_path() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(tmp_path)
    assert data == b"\x89PNG\r\n"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_file_uri() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"JFIF")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(f"file://{tmp_path}")
    assert data == b"JFIF"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_missing_file() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    data, filename = await channel._read_media_bytes("/nonexistent/path/image.png")
    assert data is None
    assert filename is None
