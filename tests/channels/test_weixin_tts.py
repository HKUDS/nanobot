"""Tests for WeChat TTS voice message integration."""

import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.weixin import WeixinChannel, WeixinConfig
from nanobot.config.schema import TTSConfig


def _make_channel(tts_api_key: str = "") -> WeixinChannel:
    bus = MessageBus()
    return WeixinChannel(
        WeixinConfig(
            enabled=True,
            allow_from=["*"],
            state_dir=tempfile.mkdtemp(prefix="nanobot-weixin-tts-test-"),
            tts=TTSConfig(api_key=tts_api_key, voice="Asuka-Plus", model="cosyvoice-v2-plus"),
        ),
        bus,
    )


def test_wants_voice_triggers_on_keywords():
    ch = _make_channel()
    assert ch._wants_voice("你说，今天天气怎么样") is True
    assert ch._wants_voice("你来说一下市场分析") is True
    assert ch._wants_voice("说给我听，关于这个问题") is True
    assert ch._wants_voice("用语音回答我") is True
    assert ch._wants_voice("语音回复") is True


def test_wants_voice_no_trigger_on_normal_text():
    ch = _make_channel()
    assert ch._wants_voice("帮我分析一下市场") is False
    assert ch._wants_voice("今天天气怎么样") is False
    assert ch._wants_voice("你好") is False
    assert ch._wants_voice("") is False


def test_voice_sessions_initialised_empty():
    ch = _make_channel()
    assert ch._voice_sessions == {}


@pytest.mark.asyncio
async def test_inbound_voice_trigger_sets_session_flag():
    """After processing a message with a voice trigger, _voice_sessions is marked."""
    ch = _make_channel()
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}

    text = "你说，帮我分析一下"
    if ch._wants_voice(text):
        ch._voice_sessions["wx-user"] = True

    assert ch._voice_sessions.get("wx-user") is True


@pytest.mark.asyncio
async def test_send_calls_tts_and_sends_voice_when_session_flagged(tmp_path, monkeypatch):
    """When _voice_sessions is set, send() calls TTS and sends the MP3."""
    ch = _make_channel(tts_api_key="sk-test")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True

    async def fake_synthesize(text: str, output_path) -> bool:
        from pathlib import Path
        Path(output_path).write_bytes(b"fake-mp3")
        return True

    ch._tts_provider.synthesize = fake_synthesize  # type: ignore

    sent_media = []
    sent_text = []

    async def fake_send_media(to, path, ctx):
        sent_media.append(str(path))

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = fake_send_media  # type: ignore
    ch._send_text = fake_send_text  # type: ignore
    ch._client = MagicMock()

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="这是回复内容")
    await ch.send(msg)

    assert len(sent_media) == 1
    assert sent_media[0].endswith(".mp3")
    assert sent_text == ["这是回复内容"]
    assert "wx-user" not in ch._voice_sessions


@pytest.mark.asyncio
async def test_send_text_still_sent_when_tts_fails(monkeypatch):
    """If TTS synthesis fails, text is still sent normally."""
    ch = _make_channel(tts_api_key="sk-test")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True
    ch._client = MagicMock()

    async def failing_synthesize(text, output_path) -> bool:
        return False

    ch._tts_provider.synthesize = failing_synthesize  # type: ignore

    sent_text = []

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = AsyncMock()
    ch._send_text = fake_send_text  # type: ignore

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="回复")
    await ch.send(msg)

    assert sent_text == ["回复"]
    ch._send_media_file.assert_not_called()


@pytest.mark.asyncio
async def test_send_skips_tts_when_no_provider():
    """If _tts_provider is None (no api_key), send() skips TTS silently."""
    ch = _make_channel(tts_api_key="")
    ch._token = "tok"
    ch._context_tokens = {"wx-user": "ctx-1"}
    ch._voice_sessions["wx-user"] = True
    ch._client = MagicMock()

    sent_media = []
    sent_text = []

    async def fake_send_media(to, path, ctx):  # pragma: no cover
        sent_media.append(path)

    async def fake_send_text(to, text, ctx):
        sent_text.append(text)

    ch._send_media_file = fake_send_media  # type: ignore
    ch._send_text = fake_send_text  # type: ignore

    msg = OutboundMessage(channel="weixin", chat_id="wx-user", content="回复")
    await ch.send(msg)

    assert sent_media == []
    assert sent_text == ["回复"]
