import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

import nanobot.providers.base as provider_base
from nanobot.providers.openai_codex_provider import OpenAICodexProvider, _CodexHTTPError

LANGFUSE_MISSING_WARNING = (
    "LANGFUSE_SECRET_KEY is set but langfuse is not installed; "
    "run `nanobot plugins enable langfuse` to enable tracing"
)


def _mock_codex_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_token(**_kwargs):
        return SimpleNamespace(account_id="acct", access="token")

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        fake_token,
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


class _FakeGeneration:
    def __init__(self, start_kwargs: dict[str, Any]) -> None:
        self.start_kwargs = start_kwargs
        self.update_calls: list[dict[str, Any]] = []
        self.ended = False

    def update(self, **kwargs: Any) -> None:
        self.update_calls.append(kwargs)

    def end(self) -> None:
        self.ended = True


def _install_fake_langfuse(monkeypatch: pytest.MonkeyPatch, start_generation) -> None:
    """Insert a fake ``langfuse`` module so ``from langfuse import get_client`` resolves."""
    fake_module = types.ModuleType("langfuse")
    fake_module.get_client = lambda: SimpleNamespace(start_generation=start_generation)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())


async def _fake_request_success(
    url, headers, body, verify, proxy=None, on_content_delta=None,
    on_thinking_delta=None, on_tool_call_delta=None,
) -> provider_base.LLMResponse:
    _ = url, headers, body, verify, proxy, on_content_delta, on_thinking_delta, on_tool_call_delta
    return provider_base.LLMResponse(
        content="hello",
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    )


async def test_codex_langfuse_missing_package_warns_and_call_still_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    capture = _capture_codex_warnings(monkeypatch)
    _mock_codex_token(monkeypatch)
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", _fake_request_success
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert capture.calls == [(LANGFUSE_MISSING_WARNING, ())]


async def test_codex_langfuse_disabled_when_env_var_unset(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    capture = _capture_codex_warnings(monkeypatch)
    _mock_codex_token(monkeypatch)
    find_spec_calls: list[str] = []
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: find_spec_calls.append(name),
    )
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", _fake_request_success
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert capture.calls == []
    assert find_spec_calls == []  # short-circuited before ever checking the package


async def test_codex_langfuse_success_records_generation_with_expected_fields(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs)
        generations.append(gen)
        return gen

    _install_fake_langfuse(monkeypatch, start_generation)
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", _fake_request_success
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert len(generations) == 1
    gen = generations[0]
    assert gen.start_kwargs["name"] == "codex_request"
    assert gen.start_kwargs["model"] == "gpt-5.6-sol"
    assert gen.update_calls[-1]["output"] == "hello"
    assert gen.update_calls[-1]["usage_details"] == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }
    assert gen.ended is True


async def test_codex_langfuse_error_records_generation_and_original_error_still_returned(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs)
        generations.append(gen)
        return gen

    _install_fake_langfuse(monkeypatch, start_generation)

    async def fake_request_error(*_args, **_kwargs):
        raise _CodexHTTPError("boom", status_code=500)

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", fake_request_error
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert result.error_status_code == 500
    assert len(generations) == 1
    gen = generations[0]
    assert gen.update_calls[-1]["level"] == "ERROR"
    assert gen.update_calls[-1]["status_message"] == result.content
    assert gen.ended is True


async def test_codex_langfuse_tracing_failure_does_not_break_codex_call(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    capture = _capture_codex_warnings(monkeypatch)

    def broken_start_generation(**_kwargs: Any):
        raise RuntimeError("langfuse backend unreachable")

    _install_fake_langfuse(monkeypatch, broken_start_generation)
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", _fake_request_success
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert len(capture.calls) == 1
    message, _args = capture.calls[0]
    assert "Langfuse tracing failed for Codex request" in message
