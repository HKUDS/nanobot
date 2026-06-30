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
    _dedup_reasoning_items,
    _drop_reasoning_id,
    _extract_duplicate_id,
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


# --- HKUDS/nanobot#3633: dedup reasoning items + duplicate-item 400 retry -----


def test_dedup_reasoning_items_drops_repeated_rs_ids_keeping_first() -> None:
    items = [
        {"type": "message", "id": "msg_1", "content": "hi"},
        {"type": "reasoning", "id": "rs_alpha", "encrypted_content": "first"},
        {"type": "message", "id": "msg_2", "content": "ok"},
        {"type": "reasoning", "id": "rs_alpha", "encrypted_content": "second"},
        {"type": "reasoning", "id": "rs_beta", "encrypted_content": "third"},
        {"type": "reasoning", "id": "rs_alpha", "encrypted_content": "fourth"},
    ]

    result = _dedup_reasoning_items(items)

    rs_alphas = [item for item in result if item.get("id") == "rs_alpha"]
    assert len(rs_alphas) == 1
    assert rs_alphas[0]["encrypted_content"] == "first"
    rs_betas = [item for item in result if item.get("id") == "rs_beta"]
    assert len(rs_betas) == 1
    # Non-reasoning items must pass through untouched and in order.
    assert [item.get("id") for item in result if item.get("type") == "message"] == [
        "msg_1",
        "msg_2",
    ]


def test_dedup_reasoning_items_ignores_non_reasoning_and_non_rs_ids() -> None:
    items = [
        {"type": "message", "id": "rs_alpha", "content": "not a reasoning item"},
        {"type": "message", "id": "rs_alpha", "content": "still not"},
        {"type": "reasoning", "id": "not_rs_prefix", "encrypted_content": "skip"},
        {"type": "reasoning", "id": "not_rs_prefix", "encrypted_content": "skip2"},
    ]

    result = _dedup_reasoning_items(items)

    # No rs_* id was present on a reasoning item — nothing should be dropped.
    assert result == items


def test_extract_duplicate_id_pulls_id_from_friendly_or_raw_payload() -> None:
    raw = (
        '{"error":{"type":"invalid_request_error","code":"duplicate_item",'
        '"message":"Duplicate item found with id rs_xyz789"}}'
    )

    assert _extract_duplicate_id(raw, "") == "rs_xyz789"
    assert _extract_duplicate_id("", "Duplicate item found with id rs_only_message") == (
        "rs_only_message"
    )
    assert _extract_duplicate_id("", "") is None


def test_drop_reasoning_id_removes_only_matching_reasoning_entries() -> None:
    items = [
        {"type": "reasoning", "id": "rs_keep"},
        {"type": "reasoning", "id": "rs_drop"},
        {"type": "message", "id": "rs_drop", "content": "different type — keep"},
        {"type": "reasoning", "id": "rs_drop"},
    ]

    result = _drop_reasoning_id(items, "rs_drop")

    assert result == [
        {"type": "reasoning", "id": "rs_keep"},
        {"type": "message", "id": "rs_drop", "content": "different type — keep"},
    ]


@pytest.mark.asyncio
async def test_codex_dedups_reasoning_items_before_outgoing_request(monkeypatch) -> None:
    """Outgoing payload must carry each rs_* id at most once (HKUDS/nanobot#3633)."""
    _mock_codex_token(monkeypatch)
    captured_bodies: list[dict[str, Any]] = []

    async def fake_request(
        url,
        headers,
        body,
        verify,
        on_content_delta=None,
        on_thinking_delta=None,
        on_tool_call_delta=None,
    ):
        captured_bodies.append(body)
        return "ok", [], "stop", {}, None

    def fake_convert_messages(_messages):
        return (
            "sys",
            [
                {"type": "message", "role": "user", "content": "first turn"},
                {"type": "reasoning", "id": "rs_duplicate", "encrypted_content": "a"},
                {"type": "message", "role": "assistant", "content": "answer"},
                {"type": "reasoning", "id": "rs_duplicate", "encrypted_content": "b"},
                {"type": "message", "role": "user", "content": "second turn"},
            ],
        )

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", fake_request
    )
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.convert_messages", fake_convert_messages
    )

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert len(captured_bodies) == 1
    sent_input = captured_bodies[0]["input"]
    rs_duplicates = [
        item
        for item in sent_input
        if isinstance(item, dict) and item.get("id") == "rs_duplicate"
    ]
    assert len(rs_duplicates) == 1, (
        f"expected exactly one rs_duplicate in outgoing payload, got "
        f"{len(rs_duplicates)} (full payload: {sent_input})"
    )


@pytest.mark.asyncio
async def test_codex_retries_once_on_duplicate_item_400(monkeypatch) -> None:
    """On 400 code:duplicate_item, strip the offending id and retry once."""
    _mock_codex_token(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_request(
        url,
        headers,
        body,
        verify,
        on_content_delta=None,
        on_thinking_delta=None,
        on_tool_call_delta=None,
    ):
        # Snapshot the body the caller saw on each attempt.
        calls.append({"input": list(body["input"])})
        if len(calls) == 1:
            raise _CodexHTTPError(
                "HTTP 400: Codex API request failed",
                status_code=400,
                error_code="duplicate_item",
                duplicate_id="rs_offender",
            )
        return "ok", [], "stop", {}, None

    def fake_convert_messages(_messages):
        return (
            "sys",
            [
                {"type": "message", "role": "user", "content": "first"},
                {"type": "reasoning", "id": "rs_keep", "encrypted_content": "k"},
                {"type": "reasoning", "id": "rs_offender", "encrypted_content": "x"},
            ],
        )

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", fake_request
    )
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.convert_messages", fake_convert_messages
    )

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert len(calls) == 2, "expected exactly one retry after duplicate_item 400"
    first_payload_ids = [
        item.get("id") for item in calls[0]["input"] if isinstance(item, dict)
    ]
    retry_payload_ids = [
        item.get("id") for item in calls[1]["input"] if isinstance(item, dict)
    ]
    assert "rs_offender" in first_payload_ids
    assert "rs_offender" not in retry_payload_ids
    assert "rs_keep" in retry_payload_ids


@pytest.mark.asyncio
async def test_codex_does_not_retry_when_duplicate_id_is_unknown(monkeypatch) -> None:
    """If the upstream payload didn't surface a duplicate_id, bubble through normally."""
    _mock_codex_token(monkeypatch)
    calls = 0

    async def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise _CodexHTTPError(
            "HTTP 400: Codex API request failed",
            status_code=400,
            error_code="duplicate_item",
            duplicate_id=None,
        )

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", fake_request
    )

    provider = OpenAICodexProvider()
    response = await provider.chat([{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert calls == 1


@pytest.mark.asyncio
async def test_codex_request_marks_duplicate_item_400_and_extracts_id(monkeypatch) -> None:
    """Upstream 400 duplicate-item payloads must surface as structured metadata."""
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "code": "duplicate_item",
                    "message": "Duplicate item found with id rs_abc123",
                }
            },
            request=request,
        )

    def fake_client(*, timeout: float, verify: bool) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.httpx.AsyncClient", fake_client
    )

    with pytest.raises(_CodexHTTPError) as caught:
        await _request_codex(
            "https://codex.example/responses", {}, {"input": []}, verify=True
        )

    error = caught.value
    assert error.status_code == 400
    assert error.error_code == "duplicate_item"
    assert error.duplicate_id == "rs_abc123"
