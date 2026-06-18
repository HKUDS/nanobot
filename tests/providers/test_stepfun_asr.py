"""Tests for StepFun ASR SSE transcription provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from blackcat.audio.transcription_registry import (
    get_transcription_provider,
    transcription_provider_names,
)
from blackcat.config.schema import Config
from blackcat.providers.transcription import StepFunTranscriptionProvider


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "voice.ogg"
    p.write_bytes(b"OggS\x00fake-audio-bytes")
    return p


# ---------------------------------------------------------------------------
# Defaults and base normalization
# ---------------------------------------------------------------------------


def test_stepfun_defaults() -> None:
    provider = StepFunTranscriptionProvider(api_key="sk-test")
    assert provider.api_url == "https://api.stepfun.com/v1/audio/asr/sse"
    assert provider.model == "stepaudio-2.5-asr"


def test_stepfun_api_base_overrides_url() -> None:
    provider = StepFunTranscriptionProvider(
        api_key="sk-test",
        api_base="https://api.stepfun.com/step_plan/v1/audio/asr/sse",
    )
    assert provider.api_url == "https://api.stepfun.com/step_plan/v1/audio/asr/sse"


def test_stepfun_api_base_appends_asr_path() -> None:
    provider = StepFunTranscriptionProvider(
        api_key="sk-test",
        api_base="https://api.stepfun.com/step_plan/v1",
    )
    assert provider.api_url == "https://api.stepfun.com/step_plan/v1/audio/asr/sse"


def test_stepfun_custom_model() -> None:
    provider = StepFunTranscriptionProvider(api_key="sk-test", model="stepaudio-2-asr-pro")
    assert provider.model == "stepaudio-2-asr-pro"


# ---------------------------------------------------------------------------
# Short-circuit: missing key / missing file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_short_circuits(audio_file: Path) -> None:
    with patch.dict("os.environ", {}, clear=True):
        provider = StepFunTranscriptionProvider(api_key=None)
        stream_mock = MagicMock()
        with patch("httpx.AsyncClient.stream", stream_mock):
            assert await provider.transcribe(audio_file) == ""
        stream_mock.assert_not_called()


@pytest.mark.asyncio
async def test_missing_file_short_circuits(audio_file: Path) -> None:
    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_mock = MagicMock()
    with patch("httpx.AsyncClient.stream", stream_mock):
        assert await provider.transcribe("/nonexistent/path/voice.ogg") == ""
    stream_mock.assert_not_called()


# ---------------------------------------------------------------------------
# SSE stream parsing: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_delta_then_done(audio_file: Path) -> None:
    """Simulates the real SSE event sequence: delta(s) -> text.done."""
    events = [
        {"type": "transcript.text.delta", "session_id": "s1", "text": "你"},
        {"type": "transcript.text.delta", "session_id": "s1", "text": "你好"},
        {"type": "transcript.text.done", "session_id": "s1", "text": "你好世界"},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == "你好世界"


@pytest.mark.asyncio
async def test_sse_only_done_event(audio_file: Path) -> None:
    """Single transcript.text.done event without deltas."""
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": "hello world"},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == "hello world"


@pytest.mark.asyncio
async def test_sse_error_event(audio_file: Path) -> None:
    """Error event in SSE stream returns "" immediately."""
    events = [
        {"type": "error", "session_id": "s1", "message": "audio too short"},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_sse_ignores_non_data_lines(audio_file: Path) -> None:
    """Empty lines and lines without 'data:' prefix are ignored."""
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": "result"},
    ]
    raw_lines = [
        "",                    # empty line
        "event: session.start",  # non-data event
        f"data: {json.dumps(events[0])}",
    ]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, raw_lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == "result"


@pytest.mark.asyncio
async def test_sse_malformed_json_skipped(audio_file: Path) -> None:
    """Malformed JSON in data lines are skipped gracefully."""
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": "ok"},
    ]
    raw_lines = [
        "data: not-json-at-all",
        f"data: {json.dumps(events[0])}",
    ]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, raw_lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == "ok"


# ---------------------------------------------------------------------------
# Retry contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds(audio_file: Path) -> None:
    """Transient 503 is retried, then a successful SSE stream yields text."""
    success_lines = [
        f"data: {json.dumps({'type': 'transcript.text.done', 'session_id': 's1', 'text': 'ok'})}",
    ]
    # First call: 503 (FailingResponse), second call: success (FakeResponse with lines)
    stream_cm = _make_stream_cm_sequence([503, success_lines])

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", stream_cm), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == "ok"


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(audio_file: Path) -> None:
    """Persistent 503 returns "" after all retries exhausted."""
    attempts: list[list[str] | int] = [503, 503, 503, 503]  # 4 failing HTTP responses
    stream_cm = _make_stream_cm_sequence(attempts)

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", stream_cm), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_sse_empty_text_done_returns_empty(audio_file: Path) -> None:
    """Empty text in transcript.text.done should return "" immediately, not retry."""
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": ""},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)

    with patch("httpx.AsyncClient.stream", stream_cm), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_401_returns_empty_without_retry(audio_file: Path) -> None:
    """401 is not retryable; bad credentials should fail immediately."""
    stream_cm = _make_stream_cm(401, [])
    sleep = AsyncMock()

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", stream_cm), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)

    assert result == ""
    assert stream_cm.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_retries_on_connect_error(audio_file: Path) -> None:
    """Network-level transient errors are retried."""
    success_lines = [
        f"data: {json.dumps({'type': 'transcript.text.done', 'session_id': 's1', 'text': 'ok'})}",
    ]
    call_count = [0]

    class FakeResponse:
        """Serves as both the async context manager returned by stream()
        and the response object bound in `async with ... as resp`."""
        status_code = 200
        reason_phrase = "OK"

        async def __aenter__(self) -> "FakeResponse":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def aiter_lines(self) -> Any:
            for line in success_lines:
                yield line

        def raise_for_status(self) -> None:
            pass

    def fake_stream(method: str, url: str, *args: object, **kwargs: object) -> FakeResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            raise httpx.ConnectError("boom")
        return FakeResponse()

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", fake_stream), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == "ok"
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_stepfun_in_registry() -> None:
    assert "stepfun" in transcription_provider_names()
    spec = get_transcription_provider("stepfun")
    assert spec is not None
    assert spec.default_model == "stepaudio-2.5-asr"
    assert spec.adapter == "nanobot.providers.transcription:StepFunTranscriptionProvider"


def test_config_resolves_stepfun() -> None:
    config = Config()
    config.transcription.provider = "stepfun"
    config.transcription.model = "stepaudio-2.5-asr"
    config.transcription.language = "zh"
    config.providers.stepfun.api_key = "step-test"
    config.providers.stepfun.api_base = "https://api.stepfun.com/step_plan/v1/audio/asr/sse"

    from blackcat.audio.transcription import resolve_transcription_config

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "stepfun"
    assert resolved.model == "stepaudio-2.5-asr"
    assert resolved.language == "zh"
    assert resolved.api_key == "step-test"
    assert resolved.api_base == "https://api.stepfun.com/step_plan/v1/audio/asr/sse"
    assert resolved.configured is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stream_cm(status: int, lines: list[str]) -> MagicMock:
    """Build a mock for `AsyncClient.stream` that yields *lines* as SSE."""

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = status
            self.reason_phrase = "OK" if status == 200 else "Error"

        async def __aenter__(self) -> "FakeResponse":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def aiter_lines(self) -> Any:
            for line in lines:
                yield line

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}",
                    request=httpx.Request("POST", "https://example.test"),
                    response=httpx.Response(self.status_code),
                )

    cm = MagicMock()
    cm.return_value = FakeResponse()
    return cm


def _make_stream_cm_sequence(statuses: list[str | int]) -> MagicMock:
    """Build a stream mock that fails with HTTP status ints, then succeeds with SSE lines.

    Entries in *statuses* that are ints produce a stream that raises HTTPStatusError
    after `raise_for_status()`.  The final entry (a list of SSE lines) succeeds.
    """
    remaining = list(statuses)

    class FakeResponse:
        def __init__(self, lines: list[str]) -> None:
            self._lines = lines
            self.status_code = 200
            self.reason_phrase = "OK"

        async def __aenter__(self) -> "FakeResponse":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def aiter_lines(self) -> Any:
            for line in self._lines:
                yield line

        def raise_for_status(self) -> None:
            pass

    class FailingResponse:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.reason_phrase = "Error"

        async def __aenter__(self) -> "FailingResponse":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def aiter_lines(self) -> Any:
            yield ""
            return

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    call_count = [0]

    def _next(method: str, url: str, **kwargs: object) -> Any:
        idx = min(call_count[0], len(remaining) - 1)
        entry = remaining[idx]
        call_count[0] += 1
        if isinstance(entry, int):
            return FailingResponse(entry)
        return FakeResponse(entry)

    cm = MagicMock(side_effect=_next)
    return cm
