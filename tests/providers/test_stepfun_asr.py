from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nanobot.audio.transcription_registry import (
    get_transcription_provider,
    transcription_provider_names,
)
from nanobot.config.schema import Config
from nanobot.providers.transcription import StepFunTranscriptionProvider


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "voice.ogg"
    p.write_bytes(b"OggS\x00fake-audio-bytes")
    return p


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


@pytest.mark.asyncio
async def test_sse_delta_then_done(audio_file: Path) -> None:
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
    events = [
        {"type": "error", "session_id": "s1", "message": "audio too short"},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)
    sleep = AsyncMock()

    with patch("httpx.AsyncClient.stream", stream_cm), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)

    assert result == ""
    assert stream_cm.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_sse_ignores_non_data_lines(audio_file: Path) -> None:
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": "result"},
    ]
    raw_lines = [
        "",
        "event: session.start",
        f"data: {json.dumps(events[0])}",
    ]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, raw_lines)

    with patch("httpx.AsyncClient.stream", stream_cm):
        result = await provider.transcribe(audio_file)

    assert result == "result"


@pytest.mark.asyncio
async def test_sse_malformed_json_skipped(audio_file: Path) -> None:
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected",
    [
        ([(503, [], None), (200, [], None), (200, ["data: []"], None),
          (200, ['data: {"type":"transcript.text.done","text":"ok"}'], None)], "ok"),
        ([(200, [], httpx.ReadError("lost")),
          (200, ['data: {"type":"transcript.text.done","text":"ok"}'], None)], "ok"),
        ([(200, [], None)] * 4, ""),
        ([(200, ["data: []"], None)] * 4, ""),
    ],
    ids=["mixed-budget", "read-error", "missing-final-exhaustion", "parser-exhaustion"],
)
async def test_sse_closes_each_attempt_before_backoff(monkeypatch, audio_file, scenario, expected):
    original_audio = audio_file.read_bytes()
    remaining = iter(scenario)
    streams, bodies, waits = [], [], []

    class Stream(httpx.AsyncByteStream):
        closed = False

        def __init__(self, lines, error):
            self.lines, self.error = lines, error

        async def __aiter__(self):
            for line in self.lines:
                yield (line + "\n").encode()
            if self.error is not None:
                raise self.error

        async def aclose(self):
            self.closed = True

    def handle(request):
        bodies.append(json.loads(request.content))
        status, lines, error = next(remaining)
        stream = Stream(lines, error)
        streams.append(stream)
        return httpx.Response(status, stream=stream)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

    async def sleep(delay):
        assert streams[-1].closed
        waits.append(delay)
        audio_file.write_bytes(b"changed-after-request")

    monkeypatch.setattr("nanobot.providers.transcription.httpx.AsyncClient", lambda: client)
    monkeypatch.setattr("nanobot.providers.transcription.asyncio.sleep", sleep)
    result = await StepFunTranscriptionProvider(api_key="sk-test", language="zh").transcribe(audio_file)
    assert result == expected
    assert len(bodies) == len(scenario)
    assert bodies == [bodies[0]] * len(scenario)
    assert base64.b64decode(bodies[0]["audio"]["data"]) == original_audio
    assert bodies[0]["audio"]["input"]["transcription"]["language"] == "zh"
    assert waits == [1.0, 2.0, 4.0][:len(scenario) - 1]
    assert all(stream.closed for stream in streams)
    assert client.is_closed


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(audio_file: Path) -> None:
    stream_cm = _make_stream_cm(503, [])

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    sleep = AsyncMock()
    with patch("httpx.AsyncClient.stream", stream_cm), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)

    assert result == ""
    assert stream_cm.call_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_sse_empty_text_done_returns_empty(audio_file: Path) -> None:
    events = [
        {"type": "transcript.text.done", "session_id": "s1", "text": ""},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events]

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    stream_cm = _make_stream_cm(200, lines)

    sleep = AsyncMock()
    with patch("httpx.AsyncClient.stream", stream_cm), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)

    assert result == ""
    assert stream_cm.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 501])
async def test_non_retryable_status_returns_empty(audio_file: Path, status: int) -> None:
    stream_cm = _make_stream_cm(status, [])
    sleep = AsyncMock()

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", stream_cm), patch("asyncio.sleep", sleep):
        result = await provider.transcribe(audio_file)

    assert result == ""
    assert stream_cm.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_retries_on_connect_error(audio_file: Path) -> None:
    success_lines = [
        f"data: {json.dumps({'type': 'transcript.text.done', 'session_id': 's1', 'text': 'ok'})}",
    ]
    fake_stream = MagicMock(side_effect=[
        httpx.ConnectError("boom"), _make_stream_cm(200, success_lines).return_value,
    ])

    provider = StepFunTranscriptionProvider(api_key="sk-test")
    with patch("httpx.AsyncClient.stream", fake_stream), patch(
        "asyncio.sleep", AsyncMock()
    ):
        result = await provider.transcribe(audio_file)

    assert result == "ok"
    assert fake_stream.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_backoff", [False, True], ids=["recover", "cancel-backoff"])
async def test_unread_503_socket_closes_before_backoff(monkeypatch, audio_file, cancel_backoff):
    first_closed, entered, blocked = asyncio.Event(), asyncio.Event(), asyncio.Event()
    bodies, responses, waits = [], [], []
    handlers = set()

    async def handle(reader, writer):
        handler = asyncio.current_task()
        handlers.add(handler)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = dict(line.split(b":", 1) for line in head.split(b"\r\n")[1:] if b":" in line)
            bodies.append(json.loads(await reader.readexactly(int(headers[b"Content-Length"]))))
            first = len(bodies) == 1
            if first:
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 1000000\r\n\r\nunread")
            else:
                payload = b'data: {"type":"transcript.text.done","text":"socket-ok"}\n\n'
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: "
                             + str(len(payload)).encode() + b"\r\n\r\n" + payload)
            await writer.drain()
            await reader.read()
            if first:
                first_closed.set()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(handler)

    async def response_received(response):
        responses.append(response)

    async def sleep(delay):
        waits.append(delay)
        assert responses[-1].is_closed
        await asyncio.wait_for(first_closed.wait(), timeout=2)
        entered.set()
        if cancel_backoff:
            await blocked.wait()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = httpx.AsyncClient(trust_env=False, event_hooks={"response": [response_received]})
    monkeypatch.setattr("nanobot.providers.transcription.httpx.AsyncClient", lambda: client)
    monkeypatch.setattr("nanobot.providers.transcription.asyncio.sleep", sleep)
    task = asyncio.create_task(StepFunTranscriptionProvider(
        api_key="local", api_base=f"http://127.0.0.1:{port}",
    ).transcribe(audio_file))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        if cancel_backoff:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(bodies) == 1
        else:
            assert await asyncio.wait_for(task, timeout=5) == "socket-ok"
            assert len(bodies) == 2
            assert bodies[0] == bodies[1]
        assert waits == [1.0]
        assert client.is_closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()
        server.close()
        await server.wait_closed()
        pending = list(handlers)
        for handler in pending:
            handler.cancel()
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=5)


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

    from nanobot.audio.transcription import resolve_transcription_config

    resolved = resolve_transcription_config(config)

    assert resolved.provider == "stepfun"
    assert resolved.model == "stepaudio-2.5-asr"
    assert resolved.language == "zh"
    assert resolved.api_key == "step-test"
    assert resolved.api_base == "https://api.stepfun.com/step_plan/v1/audio/asr/sse"
    assert resolved.configured is True


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
