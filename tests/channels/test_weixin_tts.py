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
