from types import SimpleNamespace

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _fake_response(
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        text=text,
    )


def test_openai_handle_error_extracts_structured_metadata() -> None:
    class FakeStatusError(Exception):
        pass

    err = FakeStatusError("boom")
    err.status_code = 409
    err.response = _fake_response(
        status_code=409,
        headers={"retry-after-ms": "250", "x-should-retry": "false"},
        text='{"error":{"type":"rate_limit_exceeded","code":"rate_limit_exceeded"}}',
    )
    err.body = {"error": {"type": "rate_limit_exceeded", "code": "rate_limit_exceeded"}}

    response = OpenAICompatProvider._handle_error(err)

    assert response.finish_reason == "error"
    assert response.error_status_code == 409
    assert response.error_type == "rate_limit_exceeded"
    assert response.error_code == "rate_limit_exceeded"
    assert response.error_retry_after_s == 0.25
    assert response.error_should_retry is False


def test_openai_handle_error_marks_timeout_kind() -> None:
    class FakeTimeoutError(Exception):
        pass

    response = OpenAICompatProvider._handle_error(FakeTimeoutError("timeout"))

    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"


def test_openai_handle_error_marks_timeout_from_message() -> None:
    class FakeAPIError(Exception):
        pass

    response = OpenAICompatProvider._handle_error(FakeAPIError("timed out after 300s"))

    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"


def test_base_error_response_marks_timeout_from_message() -> None:
    response = LLMProvider._error_response_from_exception(RuntimeError("timed out after 600s"))

    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"
    assert response.error_should_retry is True
    assert "timed out after 600s" in (response.content or "")


@pytest.mark.parametrize("detail", ["Unsupported parameter: timeout", "timeout must be positive"])
def test_parameter_named_timeout_is_not_a_timeout(detail: str) -> None:
    error = RuntimeError(detail)

    for response in (
        LLMProvider._error_response_from_exception(error),
        OpenAICompatProvider._handle_error(error),
    ):
        assert response.error_kind is None
        assert response.error_should_retry is not True


@pytest.mark.parametrize("status", [400, 404, 422])
def test_client_error_status_overrides_timeout_message(status: int) -> None:
    error = RuntimeError("validator timed out while checking invalid input")
    error.response = _fake_response(status_code=status)

    for response in (
        LLMProvider._error_response_from_exception(error),
        OpenAICompatProvider._handle_error(error),
    ):
        assert response.error_status_code == status
        assert response.error_kind is None
        assert response.error_should_retry is not True


def test_anthropic_handle_error_extracts_structured_metadata() -> None:
    class FakeStatusError(Exception):
        pass

    err = FakeStatusError("boom")
    err.status_code = 408
    err.response = _fake_response(
        status_code=408,
        headers={"retry-after": "1.5", "x-should-retry": "true"},
    )
    err.body = {"type": "error", "error": {"type": "rate_limit_error"}}

    response = AnthropicProvider._handle_error(err)

    assert response.finish_reason == "error"
    assert response.error_status_code == 408
    assert response.error_type == "rate_limit_error"
    assert response.error_retry_after_s == 1.5
    assert response.error_should_retry is True


def test_anthropic_handle_error_marks_connection_kind() -> None:
    class FakeConnectionError(Exception):
        pass

    response = AnthropicProvider._handle_error(FakeConnectionError("connection"))

    assert response.finish_reason == "error"
    assert response.error_kind == "connection"


@pytest.mark.parametrize("expected, kwargs", [
    (True, {"error_status_code": 402}),  # HTTP 402
    (True, {"error_type": "insufficient_quota"}),  # billing token
    (True, {"content": "429 You exceeded your current quota"}),  # text marker
    (False, {"error_status_code": 429, "error_type": "rate_limit_exceeded"}),  # plain rate limit
])
def test_is_arrearage_response(expected: bool, kwargs: dict) -> None:
    response = LLMResponse(finish_reason="error", **{"content": "boom", **kwargs})
    assert LLMProvider.is_arrearage_response(response) is expected
