"""Tests for transcription retry behavior on transient errors (B10)."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nanobot.audio.transcription import (
    EffectiveTranscriptionConfig,
    resolve_transcription_config,
    transcribe_audio_file,
)
from nanobot.audio.transcription_registry import (
    get_transcription_provider,
    resolve_transcription_provider,
    transcription_provider_names,
)
from nanobot.config.schema import Config
from nanobot.providers.transcription import (
    AssemblyAITranscriptionProvider,
    GroqTranscriptionProvider,
    OpenAITranscriptionProvider,
    OpenRouterTranscriptionProvider,
    XiaomiMiMoTranscriptionProvider,
    _audio_format,
    _resolve_chat_completions_url,
    _resolve_transcription_url,
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


def _json_response(
    status: int,
    payload: dict[str, object],
    *,
    method: str = "POST",
    url: str = "https://example.test/audio/transcriptions",
) -> httpx.Response:
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status, json=payload, request=request)


def test_resolver_uses_legacy_channel_provider_when_top_level_is_unset() -> None:
    config = Config()
    config.channels.transcription_provider = "openai"
    config.channels.transcription_language = "en"
    config.providers.openai.api_key = "sk-test"
    config.providers.openai.api_base = "https://proxy.example/v1"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "openai"
    assert resolved.model == "whisper-1"
    assert resolved.language == "en"
    assert resolved.api_key == "sk-test"
    assert resolved.api_base == "https://proxy.example/v1"
    assert resolved.configured is True


def test_resolver_prefers_top_level_transcription_over_legacy_channels() -> None:
    config = Config()
    config.channels.transcription_provider = "openai"
    config.channels.transcription_language = "en"
    config.transcription.provider = "groq"
    config.transcription.model = "whisper-large-v3-turbo"
    config.transcription.language = "ko"
    config.providers.groq.api_key = "gsk-test"
    config.providers.groq.api_base = "https://groq.example/openai/v1"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "groq"
    assert resolved.model == "whisper-large-v3-turbo"
    assert resolved.language == "ko"
    assert resolved.api_key == "gsk-test"
    assert resolved.api_base == "https://groq.example/openai/v1"


def test_resolver_supports_openrouter_transcription_provider() -> None:
    config = Config()
    config.transcription.provider = "openrouter"
    config.transcription.model = "nvidia/parakeet-tdt-0.6b-v3"
    config.transcription.language = "en"
    config.providers.openrouter.api_key = "sk-or-test"
    config.providers.openrouter.api_base = "https://openrouter.ai/api/v1"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "openrouter"
    assert resolved.model == "nvidia/parakeet-tdt-0.6b-v3"
    assert resolved.language == "en"
    assert resolved.api_key == "sk-or-test"
    assert resolved.api_base == "https://openrouter.ai/api/v1"


def test_resolver_supports_siliconflow_transcription_provider() -> None:
    config = Config()
    config.transcription.provider = "siliconflow"
    config.transcription.model = "TeleAI/TeleSpeechASR"
    config.transcription.language = "zh"
    config.providers.siliconflow.api_key = "sf-test"
    config.providers.siliconflow.api_base = "https://api.siliconflow.cn/v1"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "siliconflow"
    assert resolved.model == "TeleAI/TeleSpeechASR"
    assert resolved.language == "zh"
    assert resolved.api_key == "sf-test"
    assert resolved.api_base == "https://api.siliconflow.cn/v1"


def test_resolver_defaults_siliconflow_transcription_api_base() -> None:
    config = Config()
    config.transcription.provider = "siliconflow"
    config.providers.siliconflow.api_key = "sf-test"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "siliconflow"
    assert resolved.model == "FunAudioLLM/SenseVoiceSmall"
    assert resolved.api_key == "sf-test"
    assert resolved.api_base == "https://api.siliconflow.cn/v1"


def test_resolver_supports_siliconflow_transcription_api_key_env() -> None:
    config = Config()
    config.transcription.provider = "siliconflow"

    with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "sf-env-key"}, clear=True):
        resolved = resolve_transcription_config(config)

    assert resolved.provider == "siliconflow"
    assert resolved.api_key == "sf-env-key"
    assert resolved.api_base == "https://api.siliconflow.cn/v1"


def test_resolver_interpolates_env_ref_in_api_key() -> None:
    # load_config() does not interpolate ${VAR}; the transcription path receives
    # the raw config, so an env reference in the key must be resolved here rather
    # than sent verbatim to the provider (which yields a 401).
    config = Config()
    config.transcription.provider = "groq"
    config.providers.groq.api_key = "${MY_GROQ_KEY}"

    with patch.dict(os.environ, {"MY_GROQ_KEY": "gsk-real-value"}, clear=True):
        resolved = resolve_transcription_config(config)

    assert resolved.api_key == "gsk-real-value"


def test_resolver_env_ref_missing_var_degrades_to_not_configured() -> None:
    config = Config()
    config.transcription.provider = "groq"
    config.providers.groq.api_key = "${MISSING_GROQ_KEY}"

    with patch.dict(os.environ, {}, clear=True):
        resolved = resolve_transcription_config(config)

    # Unresolved reference degrades to a falsy key rather than the literal
    # "${...}" string, so the config reports itself as not configured.
    assert not resolved.api_key
    assert resolved.configured is False


def test_resolver_interpolates_env_ref_in_api_base() -> None:
    config = Config()
    config.transcription.provider = "groq"
    config.providers.groq.api_key = "gsk-test"
    config.providers.groq.api_base = "${MY_GROQ_BASE}"

    with patch.dict(os.environ, {"MY_GROQ_BASE": "https://groq.example/v1"}, clear=True):
        resolved = resolve_transcription_config(config)

    assert resolved.api_base == "https://groq.example/v1"


def test_resolver_supports_xiaomi_mimo_transcription_provider() -> None:
    config = Config()
    config.transcription.provider = "xiaomi_mimo"
    config.transcription.model = "mimo-v2.5-asr"
    config.transcription.language = "zh"
    config.providers.xiaomi_mimo.api_key = "mimo-test"
    config.providers.xiaomi_mimo.api_base = "https://api.xiaomimimo.com/v1"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "xiaomi_mimo"
    assert resolved.model == "mimo-v2.5-asr"
    assert resolved.language == "zh"
    assert resolved.api_key == "mimo-test"
    assert resolved.api_base == "https://api.xiaomimimo.com/v1"


def test_resolver_accepts_legacy_xiaomi_transcription_alias() -> None:
    config = Config()
    config.channels.transcription_provider = "xiaomi"
    config.channels.transcription_language = "zh"
    config.providers.xiaomi_mimo.api_key = "mimo-test"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "xiaomi_mimo"
    assert resolved.model == "mimo-v2.5-asr"
    assert resolved.language == "zh"
    assert resolved.api_key == "mimo-test"


def test_transcription_registry_lists_providers_and_aliases() -> None:
    siliconflow = get_transcription_provider("siliconflow")
    assert siliconflow is not None
    assert siliconflow.adapter == "nanobot.providers.transcription:OpenAITranscriptionProvider"
    assert siliconflow.load_adapter() is OpenAITranscriptionProvider
    assert siliconflow.default_model == "FunAudioLLM/SenseVoiceSmall"
    assert resolve_transcription_provider("silicon").name == "siliconflow"

    assert "assemblyai" in transcription_provider_names()
    assert get_transcription_provider("assemblyai").default_model == "universal-3-pro,universal-2"
    assert resolve_transcription_provider("mimo").name == "xiaomi_mimo"


def test_resolver_supports_assemblyai_provider_config() -> None:
    config = Config()
    config.transcription.provider = "assemblyai"
    config.transcription.model = "universal-3-pro"
    config.transcription.language = "en"
    config.providers.assemblyai.api_key = "aai-test"
    config.providers.assemblyai.api_base = "https://assembly.example/v2"

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "assemblyai"
    assert resolved.model == "universal-3-pro"
    assert resolved.language == "en"
    assert resolved.api_key == "aai-test"
    assert resolved.api_base == "https://assembly.example/v2"


@pytest.mark.asyncio
async def test_transcribe_audio_file_routes_openrouter_provider(audio_file: Path) -> None:
    captured: dict[str, object] = {}

    class StubOpenRouter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def transcribe(self, file_path: str | Path) -> str:
            captured["file_path"] = Path(file_path)
            return "openrouter ok"

    config = EffectiveTranscriptionConfig(
        enabled=True,
        provider="openrouter",
        model="nvidia/parakeet-tdt-0.6b-v3",
        language="en",
        api_key="sk-or-test",
        api_base="https://openrouter.ai/api/v1",
        max_duration_sec=120,
        max_upload_mb=25,
    )

    with patch("nanobot.providers.transcription.OpenRouterTranscriptionProvider", StubOpenRouter):
        result = await transcribe_audio_file(audio_file, config)

    assert result == "openrouter ok"
    assert captured == {
        "api_key": "sk-or-test",
        "api_base": "https://openrouter.ai/api/v1",
        "language": "en",
        "model": "nvidia/parakeet-tdt-0.6b-v3",
        "file_path": audio_file,
    }


@pytest.mark.asyncio
async def test_transcribe_audio_file_routes_xiaomi_mimo_provider(audio_file: Path) -> None:
    captured: dict[str, object] = {}

    class StubXiaomiMiMo:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def transcribe(self, file_path: str | Path) -> str:
            captured["file_path"] = Path(file_path)
            return "mimo ok"

    config = EffectiveTranscriptionConfig(
        enabled=True,
        provider="xiaomi_mimo",
        model="mimo-v2.5-asr",
        language="zh",
        api_key="mimo-test",
        api_base="https://api.xiaomimimo.com/v1",
        max_duration_sec=120,
        max_upload_mb=25,
    )

    with patch("nanobot.providers.transcription.XiaomiMiMoTranscriptionProvider", StubXiaomiMiMo):
        result = await transcribe_audio_file(audio_file, config)

    assert result == "mimo ok"
    assert captured == {
        "api_key": "mimo-test",
        "api_base": "https://api.xiaomimimo.com/v1",
        "language": "zh",
        "model": "mimo-v2.5-asr",
        "file_path": audio_file,
    }


@pytest.mark.asyncio
async def test_transcribe_audio_file_routes_assemblyai_provider(audio_file: Path) -> None:
    captured: dict[str, object] = {}

    class StubAssemblyAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def transcribe(self, file_path: str | Path) -> str:
            captured["file_path"] = Path(file_path)
            return "assembly ok"

    config = EffectiveTranscriptionConfig(
        enabled=True,
        provider="assemblyai",
        model="universal-3-pro",
        language="en",
        api_key="aai-test",
        api_base="https://assembly.example/v2",
        max_duration_sec=120,
        max_upload_mb=25,
    )

    with patch("nanobot.providers.transcription.AssemblyAITranscriptionProvider", StubAssemblyAI):
        result = await transcribe_audio_file(audio_file, config)

    assert result == "assembly ok"
    assert captured == {
        "api_key": "aai-test",
        "api_base": "https://assembly.example/v2",
        "language": "en",
        "model": "universal-3-pro",
        "file_path": audio_file,
    }


def test_resolved_transcription_repr_hides_api_key() -> None:
    config = Config()
    config.providers.groq.api_key = "gsk-secret"

    resolved = resolve_transcription_config(config)

    assert "gsk-secret" not in repr(resolved)
    assert "api_key" not in repr(resolved)


def test_resolver_keeps_enabled_and_limits_on_effective_config() -> None:
    config = Config()
    config.transcription.enabled = False
    config.transcription.max_duration_sec = 45
    config.transcription.max_upload_mb = 12

    resolved = resolve_transcription_config(config)

    assert resolved.enabled is False
    assert resolved.max_duration_sec == 45
    assert resolved.max_upload_mb == 12


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
async def test_provider_forwards_custom_model_in_multipart(audio_file: Path) -> None:
    provider = GroqTranscriptionProvider(api_key="k", model="whisper-large-v3-turbo")
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio_file)

    assert result == "ok"
    files = post.await_args_list[0].kwargs["files"]
    assert files["model"] == (None, "whisper-large-v3-turbo")


@pytest.mark.asyncio
async def test_provider_forwards_file_mime_type(tmp_path: Path) -> None:
    audio = tmp_path / "voice.webm"
    audio.write_bytes(b"audio")
    provider = GroqTranscriptionProvider(api_key="k")
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        result = await provider.transcribe(audio)

    assert result == "ok"
    files = post.await_args_list[0].kwargs["files"]
    assert files["file"] == ("voice.webm", b"audio", "audio/webm")


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


# ---------------------------------------------------------------------------
# Configurable model: forwarded to the multipart "model" field on all providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_cls,default_model",
    [(OpenAITranscriptionProvider, "whisper-1"), (GroqTranscriptionProvider, "whisper-large-v3")],
    ids=["openai", "groq"],
)
def test_multipart_provider_model_defaults_and_override(provider_cls, default_model):
    assert provider_cls(api_key="k").model == default_model
    assert provider_cls(api_key="k", model="custom-stt").model == "custom-stt"


@pytest.mark.parametrize(
    "provider_cls",
    [OpenAITranscriptionProvider, GroqTranscriptionProvider],
    ids=["openai", "groq"],
)
@pytest.mark.asyncio
async def test_multipart_provider_sends_configured_model(audio_file: Path, provider_cls) -> None:
    provider = provider_cls(api_key="k", model="my-stt-model")
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "ok"
    assert post.await_args_list[0].kwargs["files"]["model"] == (None, "my-stt-model")


# ---------------------------------------------------------------------------
# OpenRouter provider — JSON body with base64 audio + configurable STT model
# ---------------------------------------------------------------------------


def test_audio_format_maps_known_extensions() -> None:
    assert _audio_format(Path("v.oga")) == "ogg"  # Telegram voice notes
    assert _audio_format(Path("v.opus")) == "ogg"
    assert _audio_format(Path("v.mp4")) == "m4a"
    assert _audio_format(Path("v.mp3")) == "mp3"
    assert _audio_format(Path("v.wav")) == "wav"  # passthrough for unknown


def test_openrouter_defaults_and_chat_base_normalization() -> None:
    default = OpenRouterTranscriptionProvider(api_key="k")
    assert default.api_url == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert default.model == "openai/whisper-1"

    # A chat-style base (what users copy from provider config) gets the path appended.
    chat_base = OpenRouterTranscriptionProvider(api_key="k", api_base="https://openrouter.ai/api/v1")
    assert chat_base.api_url == "https://openrouter.ai/api/v1/audio/transcriptions"


@pytest.mark.asyncio
async def test_openrouter_sends_json_base64_body(audio_file: Path) -> None:
    """OpenRouter gets a JSON body with base64 audio + format — never multipart."""
    provider = OpenRouterTranscriptionProvider(
        api_key="k", model="nvidia/parakeet-tdt-0.6b-v3", language="en"
    )
    post = AsyncMock(return_value=_response(200, {"text": "hi"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "hi"
    call = post.await_args_list[0].kwargs
    assert "files" not in call  # not multipart
    body = call["json"]
    assert body["model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert body["language"] == "en"
    assert body["input_audio"]["format"] == "ogg"  # .ogg fixture
    assert base64.b64decode(body["input_audio"]["data"]) == audio_file.read_bytes()


@pytest.mark.asyncio
async def test_openrouter_omits_language_when_unset(audio_file: Path) -> None:
    provider = OpenRouterTranscriptionProvider(api_key="k", model="openai/whisper-1")
    post = AsyncMock(return_value=_response(200, {"text": "ok"}))
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "ok"
    assert "language" not in post.await_args_list[0].kwargs["json"]


@pytest.mark.asyncio
async def test_openrouter_shares_retry_contract(audio_file: Path) -> None:
    """OpenRouter goes through the same retry helper: 503 retried, then 200."""
    provider = OpenRouterTranscriptionProvider(api_key="k", model="openai/whisper-1")
    post = AsyncMock(side_effect=[_response(503), _response(200, {"text": "recovered"})])
    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "recovered"
    assert post.await_count == 2


def test_resolve_chat_completions_url_appends_path_to_base() -> None:
    default = "https://api.xiaomimimo.com/v1/chat/completions"
    assert _resolve_chat_completions_url(None, default) == default
    assert (
        _resolve_chat_completions_url("https://api.xiaomimimo.com/v1", default)
        == "https://api.xiaomimimo.com/v1/chat/completions"
    )
    assert _resolve_chat_completions_url(default, "https://x/chat/completions") == default


def test_xiaomi_mimo_defaults_and_base_normalization() -> None:
    provider = XiaomiMiMoTranscriptionProvider(api_key="k")
    assert provider.api_url == "https://api.xiaomimimo.com/v1/chat/completions"
    assert provider.model == "mimo-v2.5-asr"

    custom = XiaomiMiMoTranscriptionProvider(
        api_key="k",
        api_base="https://token-plan-sgp.xiaomimimo.com/v1",
        model="custom-asr",
    )
    assert custom.api_url == "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
    assert custom.model == "custom-asr"


@pytest.mark.asyncio
async def test_xiaomi_mimo_sends_chat_completion_audio_payload(audio_file: Path) -> None:
    provider = XiaomiMiMoTranscriptionProvider(api_key="k", language="zh")
    post = AsyncMock(
        return_value=_response(
            200,
            {"choices": [{"message": {"content": "你好"}}]},
        )
    )

    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "你好"

    call = post.await_args_list[0].kwargs
    assert "files" not in call
    body = call["json"]
    assert body["model"] == "mimo-v2.5-asr"
    assert body["asr_options"] == {"language": "zh"}
    audio = body["messages"][0]["content"][0]["input_audio"]["data"]
    assert audio.startswith("data:audio/ogg;base64,")
    assert base64.b64decode(audio.split(",", 1)[1]) == audio_file.read_bytes()


@pytest.mark.asyncio
async def test_xiaomi_mimo_shares_retry_contract(audio_file: Path) -> None:
    provider = XiaomiMiMoTranscriptionProvider(api_key="k")
    post = AsyncMock(
        side_effect=[
            _response(503),
            _response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )

    with patch("httpx.AsyncClient.post", post), patch("asyncio.sleep", AsyncMock()):
        assert await provider.transcribe(audio_file) == "ok"

    assert post.await_count == 2


def test_assemblyai_defaults_and_base_normalization() -> None:
    provider = AssemblyAITranscriptionProvider(api_key="aai-test")
    assert provider.upload_url == "https://api.assemblyai.com/v2/upload"
    assert provider.transcript_url == "https://api.assemblyai.com/v2/transcript"
    assert provider.model == "universal-3-pro,universal-2"

    custom = AssemblyAITranscriptionProvider(
        api_key="aai-test",
        api_base="https://assembly.example/v2",
        model="universal-3-pro",
    )
    assert custom.upload_url == "https://assembly.example/v2/upload"
    assert custom.transcript_url == "https://assembly.example/v2/transcript"
    assert custom.model == "universal-3-pro"


@pytest.mark.asyncio
async def test_assemblyai_uploads_creates_and_polls(audio_file: Path) -> None:
    provider = AssemblyAITranscriptionProvider(
        api_key="aai-test",
        api_base="https://assembly.example/v2",
        language="en",
        model="universal-3-pro,universal-2",
    )
    post = AsyncMock(
        side_effect=[
            _json_response(200, {"upload_url": "https://cdn.example/audio"}, url=provider.upload_url),
            _json_response(200, {"id": "tr_123"}, url=provider.transcript_url),
        ]
    )
    get = AsyncMock(
        return_value=_json_response(
            200,
            {"status": "completed", "text": "assembly ok"},
            method="GET",
            url=f"{provider.transcript_url}/tr_123",
        )
    )

    with patch("httpx.AsyncClient.post", post), patch("httpx.AsyncClient.get", get), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == "assembly ok"
    assert post.await_count == 2
    assert get.await_count == 1
    upload_call, create_call = post.await_args_list
    assert upload_call.args == ("https://assembly.example/v2/upload",)
    assert upload_call.kwargs["headers"]["Authorization"] == "aai-test"
    assert upload_call.kwargs["headers"]["Content-Type"] == "application/octet-stream"
    assert upload_call.kwargs["content"] == audio_file.read_bytes()
    assert create_call.args == ("https://assembly.example/v2/transcript",)
    assert create_call.kwargs["json"] == {
        "audio_url": "https://cdn.example/audio",
        "speech_models": ["universal-3-pro", "universal-2"],
        "language_code": "en",
    }
    assert get.await_args.args == ("https://assembly.example/v2/transcript/tr_123",)


@pytest.mark.asyncio
async def test_assemblyai_polls_until_completed(audio_file: Path) -> None:
    provider = AssemblyAITranscriptionProvider(api_key="aai-test")
    post = AsyncMock(
        side_effect=[
            _json_response(200, {"upload_url": "https://cdn.example/audio"}, url=provider.upload_url),
            _json_response(200, {"id": "tr_123"}, url=provider.transcript_url),
        ]
    )
    get = AsyncMock(
        side_effect=[
            _json_response(200, {"status": "processing"}, method="GET"),
            _json_response(200, {"status": "completed", "text": "done"}, method="GET"),
        ]
    )
    sleep = AsyncMock()

    with patch("httpx.AsyncClient.post", post), patch("httpx.AsyncClient.get", get), patch(
        "asyncio.sleep", sleep
    ):
        assert await provider.transcribe(audio_file) == "done"

    assert get.await_count == 2
    assert sleep.await_count == 1


@pytest.mark.asyncio
async def test_assemblyai_returns_empty_on_failed_transcript(audio_file: Path) -> None:
    provider = AssemblyAITranscriptionProvider(api_key="aai-test")
    post = AsyncMock(
        side_effect=[
            _json_response(200, {"upload_url": "https://cdn.example/audio"}, url=provider.upload_url),
            _json_response(200, {"id": "tr_123"}, url=provider.transcript_url),
        ]
    )
    get = AsyncMock(
        return_value=_json_response(
            200,
            {"status": "error", "error": "bad audio"},
            method="GET",
        )
    )

    with patch("httpx.AsyncClient.post", post), patch("httpx.AsyncClient.get", get), patch(
        "asyncio.sleep", AsyncMock()
    ):
        assert await provider.transcribe(audio_file) == ""


@pytest.mark.asyncio
async def test_assemblyai_missing_api_key_short_circuits(audio_file: Path) -> None:
    with patch.dict("os.environ", {}, clear=True):
        provider = AssemblyAITranscriptionProvider(api_key=None)
        post = AsyncMock()
        with patch("httpx.AsyncClient.post", post):
            assert await provider.transcribe(audio_file) == ""
        assert post.await_count == 0


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
# apiBase normalization (#3637): a chat-style base must not be POSTed verbatim
# ---------------------------------------------------------------------------


def test_resolve_transcription_url_falls_back_to_default() -> None:
    default = "https://api.openai.com/v1/audio/transcriptions"
    assert _resolve_transcription_url(None, default) == default
    assert _resolve_transcription_url("", default) == default


def test_resolve_transcription_url_appends_path_to_chat_style_base() -> None:
    assert (
        _resolve_transcription_url("https://api.groq.com/openai/v1", "https://x/audio/transcriptions")
        == "https://api.groq.com/openai/v1/audio/transcriptions"
    )
    # Trailing slash must not produce a doubled separator.
    assert (
        _resolve_transcription_url("https://api.groq.com/openai/v1/", "https://x/audio/transcriptions")
        == "https://api.groq.com/openai/v1/audio/transcriptions"
    )


def test_resolve_transcription_url_keeps_full_endpoint() -> None:
    full = "https://api.groq.com/openai/v1/audio/transcriptions"
    assert _resolve_transcription_url(full, "https://x/audio/transcriptions") == full


def test_groq_provider_normalizes_chat_style_api_base() -> None:
    """Regression for #3637: apiBase set to the v1 base resolves to the audio endpoint."""
    provider = GroqTranscriptionProvider(api_key="gsk-test", api_base="https://api.groq.com/openai/v1")
    assert provider.api_url == "https://api.groq.com/openai/v1/audio/transcriptions"
