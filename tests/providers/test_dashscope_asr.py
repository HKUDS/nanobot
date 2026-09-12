"""Tests for the DashScope (Bailian) native ASR transcription provider."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nanobot.audio.transcription_registry import (
    get_transcription_provider,
    resolve_transcription_provider,
    transcription_provider_names,
)
from nanobot.providers.transcription import DashScopeTranscriptionProvider


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"ID3\x03fake-audio-bytes")
    return p


_NATIVE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)


# ---------------------------------------------------------------------------
# Defaults and base normalization
# ---------------------------------------------------------------------------


def test_dashscope_defaults() -> None:
    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    assert provider.api_url == _NATIVE_URL
    assert provider.model == "qwen3-asr-flash"


def test_dashscope_base_normalized_from_compatible_mode() -> None:
    """A compatible-mode apiBase must be normalized to the host root."""
    provider = DashScopeTranscriptionProvider(
        api_key="sk-test",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert provider.api_url == _NATIVE_URL


def test_dashscope_custom_model_and_language() -> None:
    provider = DashScopeTranscriptionProvider(
        api_key="sk-test",
        model="qwen3-asr-flash-filetrans",
        language="zh",
    )
    assert provider.model == "qwen3-asr-flash-filetrans"
    assert provider.language == "zh"


# ---------------------------------------------------------------------------
# Short-circuit: missing key / missing file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_short_circuits(audio_file: Path) -> None:
    with patch.dict("os.environ", {}, clear=True):
        provider = DashScopeTranscriptionProvider(api_key=None)
        post_mock = AsyncMock()
        with patch("httpx.AsyncClient.post", post_mock):
            assert await provider.transcribe(audio_file) == ""
        post_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_file_short_circuits() -> None:
    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    post_mock = AsyncMock()
    with patch("httpx.AsyncClient.post", post_mock):
        assert await provider.transcribe("/nonexistent/voice.mp3") == ""
    post_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Request shape and response parsing
# ---------------------------------------------------------------------------


def _post_mock(payload: dict[str, Any], status: int = 200) -> tuple[MagicMock, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = status
        reason_phrase = "OK" if status < 400 else "Error"

        def json(self) -> dict[str, Any]:
            return payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}",
                    request=httpx.Request("POST", _NATIVE_URL),
                    response=httpx.Response(self.status_code),
                )

    async def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    return MagicMock(side_effect=fake_post), calls


@pytest.mark.asyncio
async def test_transcribe_happy_path(audio_file: Path) -> None:
    payload = {
        "output": {
            "choices": [{
                "message": {"role": "assistant", "content": [{"text": "你好世界"}]},
            }],
        },
        "request_id": "r1",
    }
    mock, calls = _post_mock(payload)

    provider = DashScopeTranscriptionProvider(api_key="sk-test", language="zh")
    with patch("httpx.AsyncClient.post", mock):
        result = await provider.transcribe(audio_file)

    assert result == "你好世界"
    call = calls[0]
    assert call["url"] == _NATIVE_URL
    assert call["headers"]["Authorization"] == "Bearer sk-test"

    body = call["json"]
    assert body["model"] == "qwen3-asr-flash"
    assert body["parameters"]["format"] == "mp3"
    assert body["parameters"]["asr_options"]["enable_itn"] is True
    assert body["parameters"]["asr_options"]["language"] == "zh"

    audio_block = body["input"]["messages"][0]["content"][0]
    expected_prefix = "data:audio/mpeg;base64,"
    assert audio_block["audio"].startswith(expected_prefix)
    encoded = audio_block["audio"][len(expected_prefix):]
    assert base64.b64decode(encoded) == audio_file.read_bytes()


@pytest.mark.asyncio
async def test_transcribe_string_content(audio_file: Path) -> None:
    payload = {
        "output": {"choices": [{"message": {"content": "hello world"}}]},
    }
    mock, _ = _post_mock(payload)

    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.post", mock):
        assert await provider.transcribe(audio_file) == "hello world"


@pytest.mark.asyncio
async def test_transcribe_logical_error_returns_empty(audio_file: Path) -> None:
    payload = {"code": "InvalidApiKey", "message": "Invalid API-key provided."}
    mock, _ = _post_mock(payload)

    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.post", mock):
        assert await provider.transcribe(audio_file) == ""


@pytest.mark.asyncio
async def test_transcribe_http_401_no_retry(audio_file: Path) -> None:
    mock, calls = _post_mock({}, status=401)

    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    sleep = AsyncMock()
    with patch("httpx.AsyncClient.post", mock), patch("asyncio.sleep", sleep):
        assert await provider.transcribe(audio_file) == ""

    assert len(calls) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcribe_retries_503_then_succeeds(audio_file: Path) -> None:
    success = {
        "output": {"choices": [{"message": {"content": "ok"}}]},
    }
    attempt = [0]
    calls: list[int] = []

    class FakeResponse:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.reason_phrase = "OK" if status < 400 else "Error"

        def json(self) -> dict[str, Any]:
            return success

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}",
                    request=httpx.Request("POST", _NATIVE_URL),
                    response=httpx.Response(self.status_code),
                )

    async def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        attempt[0] += 1
        calls.append(attempt[0])
        return FakeResponse(503 if attempt[0] == 1 else 200)

    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.post", MagicMock(side_effect=fake_post)), patch(
        "asyncio.sleep", AsyncMock()
    ):
        assert await provider.transcribe(audio_file) == "ok"
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_transcribe_oversized_file_returns_empty(tmp_path: Path) -> None:
    big = tmp_path / "big.mp3"
    big.write_bytes(b"\x00" * (10 * 1024 * 1024 + 1))
    post_mock = AsyncMock()

    provider = DashScopeTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.post", post_mock):
        assert await provider.transcribe(big) == ""
    post_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_dashscope_in_registry() -> None:
    assert "dashscope" in transcription_provider_names()
    spec = get_transcription_provider("dashscope")
    assert spec is not None
    assert spec.default_model == "qwen3-asr-flash"
    assert spec.adapter == "nanobot.providers.transcription:DashScopeTranscriptionProvider"
    # aliases
    assert resolve_transcription_provider("bailian") is spec
    assert resolve_transcription_provider("dashscope_native") is spec


def test_config_resolves_dashscope_key() -> None:
    from nanobot.audio.transcription import resolve_transcription_config
    from nanobot.config.schema import Config

    config = Config()
    config.transcription.provider = "dashscope"
    config.transcription.model = "qwen3-asr-flash"
    config.providers.dashscope.api_key = "ds-key"

    resolved = resolve_transcription_config(config)
    assert resolved.provider == "dashscope"
    assert resolved.api_key == "ds-key"
    assert resolved.configured is True


def test_asr_text_extraction_shapes() -> None:
    from nanobot.providers.transcription import _dashscope_asr_text

    assert _dashscope_asr_text({"output": {"choices": [{"message": {"content": "x"}}]}}) == "x"
    assert _dashscope_asr_text(
        {"output": {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}}
    ) == "ab"
    assert _dashscope_asr_text({}) == ""
    assert _dashscope_asr_text(None) == ""
    assert _dashscope_asr_text(json.loads('{"output": {"choices": []}}')) == ""
