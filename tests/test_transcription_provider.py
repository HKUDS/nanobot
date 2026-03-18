from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.providers.transcription import GroqTranscriptionProvider


class _FakeResponse:
    def __init__(self, text: str = "transcribed"):
        self._text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"text": self._text}


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, raises: Exception | None = None):
        self._response = response or _FakeResponse()
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if self._raises:
            raise self._raises
        return self._response


async def test_transcription_no_api_key_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqTranscriptionProvider(api_key=None)
    out = await provider.transcribe(tmp_path / "a.wav")
    assert out == ""


async def test_transcription_missing_file_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqTranscriptionProvider(api_key="gsk_test")
    out = await provider.transcribe(tmp_path / "missing.wav")
    assert out == ""


async def test_transcription_wrong_prefix_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqTranscriptionProvider(api_key="xai-wrong-provider")
    assert provider.api_key is None
    out = await provider.transcribe(tmp_path / "a.wav")
    assert out == ""


async def test_transcription_env_var_preferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_from_env")
    provider = GroqTranscriptionProvider(api_key="gsk_from_arg")
    assert provider.api_key == "gsk_from_env"


async def test_transcription_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")
    provider = GroqTranscriptionProvider(api_key="gsk_test")

    monkeypatch.setattr(
        "nanobot.providers.transcription.httpx.AsyncClient",
        lambda: _FakeClient(_FakeResponse("ok text")),
    )

    out = await provider.transcribe(audio)
    assert out == "ok text"


async def test_transcription_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")
    provider = GroqTranscriptionProvider(api_key="gsk_test")

    monkeypatch.setattr(
        "nanobot.providers.transcription.httpx.AsyncClient",
        lambda: _FakeClient(raises=RuntimeError("network")),
    )

    out = await provider.transcribe(audio)
    assert out == ""
