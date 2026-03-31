"""Tests for CosyVoiceTTSProvider."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.config.schema import TTSConfig
from nanobot.providers.tts import CosyVoiceTTSProvider


def _provider(api_key: str = "sk-test") -> CosyVoiceTTSProvider:
    return CosyVoiceTTSProvider(TTSConfig(api_key=api_key, voice="Asuka-Plus", model="cosyvoice-v2-plus"))


@pytest.mark.asyncio
async def test_cosyvoice_no_api_key_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = CosyVoiceTTSProvider(TTSConfig(api_key=""))
    result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_import_error_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    with patch.dict("sys.modules", {"dashscope": None, "dashscope.audio": None, "dashscope.audio.tts_v3": None}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_empty_audio_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_result = MagicMock()
    mock_result.get_audio_data.return_value = None
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.return_value = mock_result
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False


@pytest.mark.asyncio
async def test_cosyvoice_happy_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_result = MagicMock()
    mock_result.get_audio_data.return_value = b"fake-mp3-bytes"
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.return_value = mock_result
    out = tmp_path / "voice.mp3"
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("你好，世界", out)
    assert result is True
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-bytes"


@pytest.mark.asyncio
async def test_cosyvoice_api_exception_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    provider = _provider()
    mock_synthesizer = MagicMock()
    mock_synthesizer.call.side_effect = RuntimeError("API error")
    with patch.dict("sys.modules", {"dashscope": MagicMock(), "dashscope.audio": MagicMock(), "dashscope.audio.tts_v3": MagicMock(SpeechSynthesizer=mock_synthesizer)}):
        result = await provider.synthesize("hello", tmp_path / "out.mp3")
    assert result is False
