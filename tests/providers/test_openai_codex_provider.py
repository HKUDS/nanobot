from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from loguru import logger

import nanobot.providers.base as provider_base
from nanobot.providers.openai_codex_provider import (
    OpenAICodexProvider,
    _build_reasoning_options,
    _codex_error_response,
    _CodexHTTPError,
    _friendly_error,
    _request_codex,
    _should_retry_status,
)


def _mock_codex_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda: SimpleNamespace(account_id="acct", access="token"),
    )


class _WarningCaptureLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args[0], args[1:]))

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("Codex diagnostics must not log exception tracebacks")


def _capture_codex_warnings(monkeypatch: pytest.MonkeyPatch) -> _WarningCaptureLogger:
    capture = _WarningCaptureLogger()
    monkeypatch.setattr("nanobot.providers.openai_codex_provider.logger", capture)
    return capture


def test_codex_blank_timeout_root_cause_reproduction() -> None:
    """Document why upstream produced a bare ``Error calling Codex:`` message."""
    exc = httpx.ReadTimeout("")
    legacy_content = f"Error calling Codex: {exc}"

    assert str(exc) == ""
    assert legacy_content == "Error calling Codex: "
    legacy_response = provider_base.LLMResponse(content=legacy_content, finish_reason="error")
    assert legacy_response.error_kind is None
    assert legacy_response.error_should_retry is None


def test_codex_http_friendly_error_omits_raw_body() -> None:
    raw = "raw upstream body with PRIVATE PROMPT MUST NOT APPEAR"

    message = _friendly_error(500, raw)

    assert message == "HTTP 500: Codex API request failed"
    assert "PRIVATE PROMPT MUST NOT APPEAR" not in message


@pytest.mark.asyncio
async def test_codex_request_non_200_populates_http_metadata(monkeypatch) -> None:
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "2"},
            json={"error": {"type": "rate_limit_exceeded", "code": "rate_limit_exceeded"}},
            request=request,
        )

    def fake_client(*, timeout: int, verify: bool) -> httpx.AsyncClient:
        assert timeout == 90
        assert verify is True
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("nanobot.providers.openai_codex_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(_CodexHTTPError) as caught:
        await _request_codex("https://codex.example/responses", {}, {"input": []}, verify=True)

    error = caught.value
    assert str(error) == "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    assert error.status_code == 429
    assert error.retry_after == 2.0
    assert error.error_type == "rate_limit_exceeded"
    assert error.error_code == "rate_limit_exceeded"
    assert error.should_retry is True


@pytest.mark.asyncio
async def test_codex_request_honors_stream_idle_timeout_env(monkeypatch) -> None:
    """NANOBOT_STREAM_IDLE_TIMEOUT_S overrides the default Codex stream timeout."""
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "5")
    original_client = httpx.AsyncClient
    seen: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    def fake_client(*, timeout: int, verify: bool) -> httpx.AsyncClient:
        seen["timeout"] = timeout
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("nanobot.providers.openai_codex_provider.httpx.AsyncClient", fake_client)

    await _request_codex("https://codex.example/responses", {}, {"input": []}, verify=True)

    assert seen["timeout"] == 5


@pytest.mark.asyncio
async def test_codex_prompt_cache_key_uses_stable_conversation_prefix(monkeypatch) -> None:
    bodies: list[dict] = []

    _mock_codex_token(monkeypatch)

    async def fake_request(
        url,
        headers,
        body,
        verify,
        on_content_delta=None,
        on_thinking_delta=None,
        on_tool_call_delta=None,
    ):
        _ = on_thinking_delta, on_tool_call_delta
        bodies.append(body)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first answer"},
        ],
    )
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow up"},
        ],
    )
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "different request"},
            {"role": "assistant", "content": "first answer"},
        ],
    )

    assert bodies[0]["prompt_cache_key"] == bodies[1]["prompt_cache_key"]
    assert bodies[0]["prompt_cache_key"] != bodies[2]["prompt_cache_key"]


@pytest.mark.asyncio
async def test_codex_timeout_error_is_typed_and_retryable(monkeypatch) -> None:
    _mock_codex_token(monkeypatch)

    async def fake_request(*args, **kwargs):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert response.content == (
        "Error calling Codex (ReadTimeout): timed out waiting for response"
    )
    assert response.error_kind == "timeout"
    assert response.error_should_retry is True


@pytest.mark.asyncio
async def test_codex_timeout_error_writes_diagnostic_log(monkeypatch) -> None:
    log_capture = _capture_codex_warnings(monkeypatch)
    _mock_codex_token(monkeypatch)

    async def fake_request(*args: Any, **kwargs: Any):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.content == (
        "Error calling Codex (ReadTimeout): timed out waiting for response"
    )
    assert log_capture.calls == [
        (
            "Codex API request failed: type={} kind={} retryable={} status={} "
            "error_type={} error_code={} retry_after={} summary={}",
            (
                "ReadTimeout",
                "timeout",
                True,
                None,
                None,
                None,
                None,
                "ReadTimeout timeout",
            ),
        )
    ]


@pytest.mark.asyncio
async def test_codex_diagnostic_log_omits_prompt_content(monkeypatch) -> None:
    sink = io.StringIO()
    logger.enable("nanobot")
    handler_id = logger.add(sink, format="{message}", backtrace=True, diagnose=True)
    try:
        _mock_codex_token(monkeypatch)

        async def fake_request(*args: Any, **kwargs: Any):
            raise httpx.ReadTimeout("")

        monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

        provider = OpenAICodexProvider()
        response = await provider.chat(
            [{"role": "user", "content": "PRIVATE PROMPT MUST NOT APPEAR"}]
        )
    finally:
        logger.remove(handler_id)

    log_text = sink.getvalue()
    assert response.error_kind == "timeout"
    assert "Codex API request failed" in log_text
    assert "ReadTimeout" in log_text
    assert "PRIVATE PROMPT MUST NOT APPEAR" not in log_text


@pytest.mark.asyncio
async def test_codex_retry_uses_structured_timeout_metadata(monkeypatch) -> None:
    calls = 0
    delays: list[float] = []

    _mock_codex_token(monkeypatch)

    async def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("")
        return "ok", [], "stop", {}, None

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)
    monkeypatch.setattr(provider_base.asyncio, "sleep", fake_sleep)

    provider = OpenAICodexProvider()
    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_codex_http_error_preserves_status_and_retry_after(monkeypatch) -> None:
    _mock_codex_token(monkeypatch)

    async def fake_request(*args, **kwargs):
        raise _CodexHTTPError(
            "HTTP 503: backend unavailable",
            status_code=503,
            retry_after=2.5,
            error_type="server_error",
            error_code="overloaded",
        )

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert response.content == "Error calling Codex (CodexHTTPError): HTTP 503: backend unavailable"
    assert response.error_status_code == 503
    assert response.error_kind == "http"
    assert response.error_type == "server_error"
    assert response.error_code == "overloaded"
    assert response.retry_after == 2.5
    assert response.error_should_retry is True


@pytest.mark.asyncio
async def test_codex_http_diagnostic_log_omits_raw_body(monkeypatch) -> None:
    log_capture = _capture_codex_warnings(monkeypatch)
    _mock_codex_token(monkeypatch)

    async def fake_request(*args: Any, **kwargs: Any):
        raise _CodexHTTPError(
            _friendly_error(500, "raw upstream body with PRIVATE PROMPT MUST NOT APPEAR"),
            status_code=500,
            error_type="server_error",
            error_code="overloaded",
        )

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.content == "Error calling Codex (CodexHTTPError): HTTP 500: Codex API request failed"
    assert log_capture.calls == [
        (
            "Codex API request failed: type={} kind={} retryable={} status={} "
            "error_type={} error_code={} retry_after={} summary={}",
            (
                "CodexHTTPError",
                "http",
                True,
                500,
                "server_error",
                "overloaded",
                None,
                "HTTP 500 type=server_error code=overloaded",
            ),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "error_code", "expected_retry"),
    [
        ("rate_limit_exceeded", "rate_limit_exceeded", True),
        ("insufficient_quota", "insufficient_quota", False),
    ],
)
async def test_codex_429_preserves_retry_semantics(
    monkeypatch,
    error_type: str,
    error_code: str,
    expected_retry: bool,
) -> None:
    _mock_codex_token(monkeypatch)

    async def fake_request(*args: Any, **kwargs: Any):
        raise _CodexHTTPError(
            "ChatGPT usage quota exceeded or rate limit triggered. Please try again later.",
            status_code=429,
            error_type=error_type,
            error_code=error_code,
            should_retry=expected_retry,
        )

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.error_status_code == 429
    assert response.error_type == error_type
    assert response.error_code == error_code
    assert response.error_should_retry is expected_retry


def test_codex_429_friendly_message_fallback_does_not_override_unknown_retry() -> None:
    response = _codex_error_response(
        _CodexHTTPError(_friendly_error(429, ""), status_code=429)
    )

    assert response.error_status_code == 429
    assert response.error_should_retry is True


@pytest.mark.parametrize(
    ("raw", "expected_retry"),
    [
        ('{"error":{"type":"rate_limit_exceeded","code":"rate_limit_exceeded"}}', True),
        ('{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}', False),
    ],
)
def test_codex_429_classification_uses_raw_error_semantics(
    raw: str,
    expected_retry: bool,
) -> None:
    error_type, error_code = provider_base.LLMProvider._extract_error_type_code(raw)

    assert _should_retry_status(429, error_type, error_code, raw) is expected_retry


def test_codex_reasoning_options_request_summary_without_forcing_effort() -> None:
    assert _build_reasoning_options(None) == {"summary": "auto"}
    assert _build_reasoning_options("high") == {"summary": "auto", "effort": "high"}
    assert _build_reasoning_options("none") == {"effort": "none"}


@pytest.mark.asyncio
async def test_codex_stream_surfaces_reasoning_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda: SimpleNamespace(account_id="acct", access="token"),
    )

    async def fake_request(
        url,
        headers,
        body,
        verify,
        on_content_delta=None,
        on_thinking_delta=None,
        on_tool_call_delta=None,
    ):
        _ = url, headers, verify, on_tool_call_delta
        assert body["reasoning"] == {"summary": "auto", "effort": "medium"}
        if on_content_delta:
            await on_content_delta("answer")
        if on_thinking_delta:
            await on_thinking_delta("summary")
        return "answer", [], "stop", {"prompt_tokens": 10, "completion_tokens": 5}, "summary"

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    content_deltas: list[str] = []
    thinking_deltas: list[str] = []

    response = await provider.chat_stream(
        [{"role": "user", "content": "hi"}],
        reasoning_effort="medium",
        on_content_delta=lambda delta: _append(content_deltas, delta),
        on_thinking_delta=lambda delta: _append(thinking_deltas, delta),
    )

    assert content_deltas == ["answer"]
    assert thinking_deltas == ["summary"]
    assert response.content == "answer"
    assert response.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert response.reasoning_content == "summary"


async def _append(target: list[str], value: str) -> None:
    target.append(value)
