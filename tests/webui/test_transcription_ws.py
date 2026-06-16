"""Tests for WebUI transcription envelopes carried over the gateway socket."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from blackcat.config.loader import save_config
from blackcat.config.schema import Config
from blackcat.webui.transcription_ws import webui_transcription_event


def _audio_data_url(payload: bytes = b"voice", mime: str = "audio/webm") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


@pytest.mark.asyncio
async def test_webui_transcribe_audio_rejects_unconfigured_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "groq"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    event, payload = await webui_transcription_event({
        "request_id": "voice-1",
        "data_url": _audio_data_url(),
    })

    assert event == "transcription_error"
    assert payload == {
        "request_id": "voice-1",
        "detail": "not_configured",
        "provider": "groq",
    }


@pytest.mark.asyncio
async def test_webui_transcribe_audio_rejects_unsupported_mime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "groq"
    config.providers.groq.api_key = "gsk-test"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    event, payload = await webui_transcription_event({
        "request_id": "voice-1",
        "data_url": _audio_data_url(mime="text/plain"),
    })

    assert event == "transcription_error"
    assert payload["request_id"] == "voice-1"
    assert payload["detail"] == "mime"


@pytest.mark.asyncio
async def test_webui_transcribe_audio_rejects_oversized_audio(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "groq"
    config.transcription.max_upload_mb = 1
    config.providers.groq.api_key = "gsk-test"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr("blackcat.audio.transcription.get_media_dir", lambda _channel=None: tmp_path)

    event, payload = await webui_transcription_event({
        "request_id": "voice-1",
        "data_url": _audio_data_url(payload=b"x" * (1024 * 1024 + 1)),
    })

    assert event == "transcription_error"
    assert payload["request_id"] == "voice-1"
    assert payload["detail"] == "size"


@pytest.mark.asyncio
async def test_webui_transcribe_audio_returns_text_and_removes_temp_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    config = Config()
    config.transcription.provider = "groq"
    config.providers.groq.api_key = "gsk-test"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "blackcat.audio.transcription.get_media_dir",
        lambda _channel=None: media_dir,
    )
    captured_paths: list[Path] = []

    async def fake_transcribe_audio_file(path: str | Path, _resolved: Any) -> str:
        p = Path(path)
        assert p.exists()
        captured_paths.append(p)
        return "hello voice"

    monkeypatch.setattr(
        "blackcat.audio.transcription.transcribe_audio_file",
        fake_transcribe_audio_file,
    )

    event, payload = await webui_transcription_event({
        "request_id": "voice-1",
        "data_url": _audio_data_url(payload=b"webm voice", mime="audio/webm;codecs=opus"),
        "duration_ms": 1200,
    })

    assert event == "transcription_result"
    assert payload == {"request_id": "voice-1", "text": "hello voice"}
    assert captured_paths
    assert not captured_paths[0].exists()
