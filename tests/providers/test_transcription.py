"""Tests for transcription retry behavior on transient errors (B10)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nanobot.providers.transcription import (
    FasterWhisperTranscriptionProvider,
    GroqTranscriptionProvider,
    OpenAITranscriptionProvider,
)


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "voice.ogg"
    p.write_bytes(b"OggS\x00fake-audio-bytes")
    return p


def _response(status: int, payload: dict[str, object] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test/audio/transcriptions")
    return httpx.Response(status_code=status, json=payload or {}, request=request)


def _raw_response(status: int, content: bytes) -> httpx.Response:
    """Build a Response with a raw, possibly-malformed body (bypasses json= encoding)."""
    request = httpx.Request("POST", "https://example.test/audio/transcriptions")
    return httpx.Response(status_code=status, content=content, request=request)


# ---------------------------------------------------------------------------
# OpenAI provider — retry on transient HTTP + network errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_retries_on_5xx_then_succeeds(audio_file: Path) -> None:
    """Transient 503 is retried; a subsequent 200 yields the text."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(side_effect=[_response(503), _response(200, {"text": "hello"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "hello"
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_openai_retries_on_429_then_succeeds(audio_file: Path) -> None:
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(side_effect=[_response(429), _response(200, {"text": "rate ok"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "rate ok"
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_openai_retries_on_connect_error(audio_file: Path) -> None:
    """Network-level transient errors are retried."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(side_effect=[httpx.ConnectError("boom"), _response(200, {"text": "ok"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "ok"
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_openai_does_not_retry_on_auth_error(audio_file: Path) -> None:
    """401 is the user's misconfiguration — retrying wastes time and rate-limit quota."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(return_value=_response(401, {"error": {"message": "bad key"}}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == ""
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_openai_gives_up_after_max_attempts(audio_file: Path) -> None:
    """Persistent 503 returns "" after the final retry — never hangs."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(return_value=_response(503))
    sleep = AsyncMock()
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)
    assert result == ""
    # 4 attempts total (initial + 3 retries) with 3 sleeps between them.
    assert post.await_count == 4
    assert sleep.await_count == 3


@pytest.mark.asyncio
async def test_openai_backoff_grows_exponentially(audio_file: Path) -> None:
    """Verify the backoff schedule is exponential (1s, 2s, 4s)."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(return_value=_response(503))
    sleep = AsyncMock()
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", sleep):
        await provider.transcribe(audio_file)
    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# Groq provider — same semantics (both go through the shared helper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_retries_on_5xx_then_succeeds(audio_file: Path) -> None:
    provider = GroqTranscriptionProvider(api_key="gsk-test")
    post = AsyncMock(side_effect=[_response(502), _response(200, {"text": "groq ok"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "groq ok"
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_groq_does_not_retry_on_auth_error(audio_file: Path) -> None:
    provider = GroqTranscriptionProvider(api_key="gsk-test")
    post = AsyncMock(return_value=_response(403))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == ""
    assert post.await_count == 1


# ---------------------------------------------------------------------------
# Regression: missing file / missing key must still short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_missing_api_key_short_circuits(audio_file: Path) -> None:
    """Missing API key short-circuits before any HTTP call, even when the file exists."""
    with patch.dict("os.environ", {}, clear=True):
        provider = OpenAITranscriptionProvider(api_key=None)
        post = AsyncMock()
        with patch("httpx.AsyncClient.post", post):
            assert await provider.transcribe(audio_file) == ""
        assert post.await_count == 0


@pytest.mark.asyncio
async def test_openai_missing_file_short_circuits() -> None:
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock()
    with patch("httpx.AsyncClient.post", post):
        assert await provider.transcribe("/nonexistent/path/voice.ogg") == ""
    assert post.await_count == 0


@pytest.mark.asyncio
async def test_returns_empty_when_file_unreadable(audio_file: Path) -> None:
    """Existing file that cannot be read (PermissionError/OSError): "" with no HTTP attempt."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock()
    with patch("pathlib.Path.read_bytes", side_effect=PermissionError("denied")), patch(
        "httpx.AsyncClient.post", post
    ):
        result = await provider.transcribe(audio_file)
    assert result == ""
    assert post.await_count == 0


# ---------------------------------------------------------------------------
# language: forwarded through the helper to the multipart body, on every attempt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_cls,language",
    [(OpenAITranscriptionProvider, "en"), (GroqTranscriptionProvider, "ko")],
    ids=["openai", "groq"],
)
@pytest.mark.asyncio
async def test_provider_forwards_language_in_multipart(
    audio_file: Path, provider_cls: type, language: str
) -> None:
    """When ``language`` is set, the helper sends it as a multipart field."""
    provider = provider_cls(api_key="k", language=language)
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "ok"
    assert post.await_count == 1
    files = post.await_args_list[0].kwargs["files"]
    assert files["language"] == (None, language)


@pytest.mark.parametrize(
    "provider_cls",
    [OpenAITranscriptionProvider, GroqTranscriptionProvider],
    ids=["openai", "groq"],
)
@pytest.mark.asyncio
async def test_provider_omits_language_when_unset(
    audio_file: Path, provider_cls: type
) -> None:
    """When ``language`` is None, no ``language`` field is sent."""
    provider = provider_cls(api_key="k")
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "ok"
    assert post.await_count == 1
    files = post.await_args_list[0].kwargs["files"]
    assert "language" not in files


@pytest.mark.asyncio
async def test_language_survives_retry(audio_file: Path) -> None:
    """Regression: language must be present on every retry attempt, not just the first."""
    provider = OpenAITranscriptionProvider(api_key="sk-test", language="ja")
    post = AsyncMock(side_effect=[_response(503), _response(200, {"text": "konnichiwa"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "konnichiwa"
    assert post.await_count == 2
    for call in post.await_args_list:
        assert call.kwargs["files"]["language"] == (None, "ja")


# ---------------------------------------------------------------------------
# Malformed / unexpected response bodies must short-circuit, not escape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_on_malformed_json_body(audio_file: Path) -> None:
    """200 with invalid JSON: log and return "" immediately (no retry, no exception)."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(return_value=_raw_response(200, b"<html>not json</html>"))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == ""
    assert post.await_count == 1


# ---------------------------------------------------------------------------
# faster-whisper local provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_faster_whisper_missing_file_short_circuits(
    _reset_faster_whisper_cache,
) -> None:
    provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="cpu")
    result = await provider.transcribe("/nonexistent/path/voice.ogg")
    assert result == ""


@pytest.mark.asyncio
async def test_faster_whisper_import_error_returns_empty(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """If faster-whisper is not installed, return empty string gracefully."""
    provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="cpu")
    import sys
    saved = sys.modules.pop("faster_whisper", None)
    try:
        # Ensure the module cannot be imported
        class _BlockImport:
            def find_module(self, name, path=None):
                if name == "faster_whisper":
                    return self
                return None
            def load_module(self, name):
                raise ImportError("No module named faster-whisper")
        blocker = _BlockImport()
        sys.meta_path.insert(0, blocker)
        try:
            result = await provider.transcribe(audio_file)
        finally:
            sys.meta_path.remove(blocker)
    finally:
        if saved is not None:
            sys.modules["faster_whisper"] = saved
    assert result == ""


@pytest.mark.asyncio
async def test_faster_whisper_auto_device_no_cuda(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """When torch is installed but has no CUDA, device falls back to cpu."""
    import sys
    saved = sys.modules.pop("torch", None)
    try:
        import types
        mock_cuda = types.SimpleNamespace(is_available=Mock(return_value=False))
        mock_torch = types.SimpleNamespace(cuda=mock_cuda)
        sys.modules["torch"] = mock_torch
        provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="auto")
        assert provider._effective_device == "cpu"
    finally:
        if saved is not None:
            sys.modules["torch"] = saved
        else:
            sys.modules.pop("torch", None)


@pytest.mark.asyncio
async def test_faster_whisper_auto_device_with_cuda(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """When torch detects CUDA, device is cuda."""
    import sys
    saved = sys.modules.pop("torch", None)
    try:
        import types
        mock_cuda = types.SimpleNamespace(is_available=Mock(return_value=True))
        mock_torch = types.SimpleNamespace(cuda=mock_cuda)
        sys.modules["torch"] = mock_torch
        provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="auto")
        assert provider._effective_device == "cuda"
    finally:
        if saved is not None:
            sys.modules["torch"] = saved
        else:
            sys.modules.pop("torch", None)


@pytest.mark.asyncio
async def test_faster_whisper_auto_device_torch_not_installed(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """When torch is not installed at all, device falls back to cpu."""
    import sys
    saved = sys.modules.pop("torch", None)
    try:
        provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="auto")
        assert provider._effective_device == "cpu"
    finally:
        if saved is not None:
            sys.modules["torch"] = saved
    

@pytest.mark.asyncio
async def test_faster_whisper_explicit_device_overrides_auto(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """Explicit device setting takes precedence over auto-detection."""
    provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="cuda")
    assert provider._effective_device == "cuda"


@pytest.mark.asyncio
async def test_returns_empty_on_non_dict_json_body(audio_file: Path) -> None:
    """200 with a JSON array (not dict): no AttributeError leak; return "" immediately."""
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(return_value=_raw_response(200, b"[]"))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == ""
    assert post.await_count == 1


# ---------------------------------------------------------------------------
# Pin the full advertised retry contract: all retryable statuses + exceptions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
@pytest.mark.asyncio
async def test_retries_on_every_advertised_transient_status(
    audio_file: Path, status: int
) -> None:
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(side_effect=[_response(status), _response(200, {"text": "ok"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "ok"
    assert post.await_count == 2


@pytest.mark.parametrize(
    "exc",
    [
        httpx.TimeoutException("t"),
        httpx.ConnectError("c"),
        httpx.ReadError("r"),
        httpx.WriteError("w"),
        httpx.RemoteProtocolError("p"),
    ],
    ids=["timeout", "connect", "read", "write", "remote_protocol"],
)
@pytest.mark.asyncio
async def test_retries_on_every_advertised_transient_exception(
    audio_file: Path, exc: Exception
) -> None:
    provider = OpenAITranscriptionProvider(api_key="sk-test")
    post = AsyncMock(side_effect=[exc, _response(200, {"text": "recovered"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)
    assert result == "recovered"
    assert post.await_count == 2


# ---------------------------------------------------------------------------
# faster-whisper — model caching and concurrency
# ---------------------------------------------------------------------------

@pytest.fixture()
def _reset_faster_whisper_cache():
    """Reset class-level state so each test starts fresh."""
    FasterWhisperTranscriptionProvider._model = None
    FasterWhisperTranscriptionProvider._last_used = 0.0
    FasterWhisperTranscriptionProvider._lock = None
    FasterWhisperTranscriptionProvider._unload_handle = None
    yield
    # Cleanup after test too
    FasterWhisperTranscriptionProvider._model = None
    FasterWhisperTranscriptionProvider._last_used = 0.0
    FasterWhisperTranscriptionProvider._lock = None
    FasterWhisperTranscriptionProvider._unload_handle = None


def _mock_whisper_model(init_counter: list[int]):
    """Factory that builds a MockModel class counting instantiations."""
    class MockSegment:
        text = "hello world"

    class MockInfo:
        language = "en"
        duration = 1.0

    class MockModel:
        def __init__(self, model_size, device):
            init_counter[0] += 1

        def transcribe(self, path, language=None, beam_size=1):
            return [MockSegment()], MockInfo()

    return MockModel


def _install_mock_whisper_model(init_counter: list[int]):
    """Install a mock faster_whisper module into sys.modules and patch it in.

    Returns a context manager (the patch) that should be used as ``with``."""
    import types

    MockModel = _mock_whisper_model(init_counter)
    mock_module = types.ModuleType("faster_whisper")
    mock_module.WhisperModel = MockModel

    return patch.dict("sys.modules", {"faster_whisper": mock_module})


@pytest.mark.asyncio
async def test_faster_whisper_model_cached_between_calls(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """WhisperModel should be instantiated only once across multiple sequential calls."""
    provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="cpu")

    init_counter = [0]

    with _install_mock_whisper_model(init_counter):
        await provider.transcribe(audio_file)
        await provider.transcribe(audio_file)
        await provider.transcribe(audio_file)

    assert init_counter[0] == 1


@pytest.mark.asyncio
async def test_faster_whisper_concurrent_calls_reuse_model(
    audio_file: Path,
    _reset_faster_whisper_cache,
) -> None:
    """Concurrent transcribe calls should not create multiple WhisperModel instances."""
    provider = FasterWhisperTranscriptionProvider(model_size="tiny", device="cpu")

    init_counter = [0]

    with _install_mock_whisper_model(init_counter):
        results = await asyncio.gather(
            provider.transcribe(audio_file),
            provider.transcribe(audio_file),
        )

    assert all(r == "hello world" for r in results)
    assert init_counter[0] == 1
