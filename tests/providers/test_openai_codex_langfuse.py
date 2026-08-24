import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

import nanobot.providers.base as provider_base
from nanobot.providers.openai_codex_provider import OpenAICodexProvider, _CodexHTTPError
from nanobot.providers.openai_responses import build_responses_state

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
    def __init__(self, start_kwargs: dict[str, Any], *, fail_update: bool = False) -> None:
        self.start_kwargs = start_kwargs
        self.update_calls: list[dict[str, Any]] = []
        self.ended = False
        self.end_calls = 0
        self._fail_update = fail_update

    def update(self, **kwargs: Any) -> None:
        self.update_calls.append(kwargs)
        if self._fail_update:
            raise RuntimeError("langfuse update failed")

    def end(self) -> None:
        self.end_calls += 1
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
        usage=provider_base.LLMUsage.reported(input_tokens=1, output_tokens=2, total_tokens=3),
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
        "input_tokens": 1,
        "output_tokens": 2,
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


async def test_codex_langfuse_generation_still_ends_when_update_raises(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    capture = _capture_codex_warnings(monkeypatch)
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs, fail_update=True)
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
    assert gen.end_calls == 1  # end() still attempted, exactly once, despite update() raising
    assert gen.ended is True
    assert len(capture.calls) == 1
    assert "Langfuse tracing failed for Codex request" in capture.calls[0][0]


async def test_codex_langfuse_generation_ends_on_cancellation(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs)
        generations.append(gen)
        return gen

    _install_fake_langfuse(monkeypatch, start_generation)

    async def fake_request_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", fake_request_cancelled
    )

    provider = OpenAICodexProvider()
    with pytest.raises(asyncio.CancelledError):
        await provider.chat([{"role": "user", "content": "hi"}])

    assert len(generations) == 1
    gen = generations[0]
    assert gen.end_calls == 1  # closed exactly once even though neither record_* method ran
    assert gen.ended is True
    assert gen.update_calls == []  # no output/usage known - nothing to attach


async def test_codex_langfuse_traces_each_request_during_native_compaction(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs)
        generations.append(gen)
        return gen

    _install_fake_langfuse(monkeypatch, start_generation)

    provider = OpenAICodexProvider(default_model="openai-codex/gpt-5.6-sol")
    state_provider = provider._responses_state_provider()
    state = build_responses_state(
        provider=state_provider,
        model="gpt-5.6-sol",
        input_items=[{"type": "message", "role": "user", "content": "old question"}],
        output_items=[
            {"type": "reasoning", "encrypted_content": "old opaque reasoning"},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "old answer"}],
            },
        ],
        usage=provider_base.LLMUsage.reported(input_tokens=90, output_tokens=5, total_tokens=95),
    )

    async def fake_request(
        url, headers, body, verify, proxy=None, on_content_delta=None,
        on_thinking_delta=None, on_tool_call_delta=None,
    ):
        _ = url, headers, verify, proxy, on_content_delta, on_thinking_delta, on_tool_call_delta
        if body["input"][-1].get("type") == "compaction_trigger":
            compact_item = {"type": "compaction", "encrypted_content": "compacted opaque state"}
            return provider_base.LLMResponse(
                content=None,
                provider_state=build_responses_state(
                    provider=state_provider,
                    model="gpt-5.6-sol",
                    input_items=body["input"],
                    output_items=[compact_item],
                    usage=provider_base.LLMUsage.reported(input_tokens=95, output_tokens=2, total_tokens=97),
                ),
            )
        return provider_base.LLMResponse(
            content="done",
            usage=provider_base.LLMUsage.reported(input_tokens=5, output_tokens=1, total_tokens=6),
        )

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    response = await provider.chat_with_retry(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "new question"},
        ],
        max_tokens=5,
        provider_context=provider_base.ProviderCallContext(
            conversation_state=state.with_pending_messages([
                {"role": "user", "content": "new question"},
            ]),
            context_window_tokens=100,
        ),
    )

    assert response.content == "done"
    # Both the compaction sub-request and the main request are real Codex
    # HTTP calls; each must get its own generation, not just the last one.
    assert len(generations) == 2
    assert generations[0].start_kwargs["name"] == "codex_compaction"
    assert generations[1].start_kwargs["name"] == "codex_request"
    assert all(gen.ended for gen in generations)
    assert generations[1].update_calls[-1]["output"] == "done"


async def test_codex_langfuse_detection_failure_does_not_break_codex_call(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    capture = _capture_codex_warnings(monkeypatch)

    def broken_find_spec(name: str):
        raise ValueError("corrupt module cache")

    monkeypatch.setattr("importlib.util.find_spec", broken_find_spec)
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex", _fake_request_success
    )

    provider = OpenAICodexProvider()
    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert len(capture.calls) == 1
    assert "Langfuse tracing failed for Codex request" in capture.calls[0][0]


async def test_codex_langfuse_traces_the_actual_wire_body_not_the_prenormalized_one(
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

    provider = OpenAICodexProvider(
        default_model="openai-codex/gpt-5.6-sol",
        extra_body={"model": "openai-codex/override-model"},
    )
    state = build_responses_state(
        provider=provider._responses_state_provider(),
        model="gpt-5.6-sol",
        input_items=[{
            "id": "msg_user",
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Check the weather"}],
        }],
        output_items=[
            {
                "id": "rs_reasoning",
                "type": "reasoning",
                "encrypted_content": "opaque reasoning",
                "summary": [],
            },
            {
                "id": "fc_read",
                "type": "function_call",
                "call_id": "call_read",
                "name": "read_file",
                "arguments": '{"path":"weather/SKILL.md"}',
                "status": "completed",
            },
        ],
    )
    sent_bodies: list[dict[str, Any]] = []

    async def fake_request(
        url, headers, body, verify, proxy=None, on_content_delta=None,
        on_thinking_delta=None, on_tool_call_delta=None,
    ):
        sent_bodies.append(body)
        return provider_base.LLMResponse(content="done")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    await provider.chat(
        [{"role": "user", "content": "Check the weather"}],
        provider_context=provider_base.ProviderCallContext(
            conversation_state=state.with_pending_messages([{
                "role": "tool",
                "tool_call_id": "call_read|fc_read",
                "content": "weather skill contents",
            }]),
        ),
    )

    assert len(sent_bodies) == 1
    wire_body = sent_bodies[0]
    assert all("id" not in item for item in wire_body["input"])
    assert len(generations) == 1
    gen = generations[0]
    # extra_body's model override must be what's traced, not the original
    # default_model argument that _extra_body overrides.
    assert gen.start_kwargs["model"] == "override-model"
    # Traced input must match the actually-sent, ID-stripped items, not the
    # pre-normalized body that still carries server-assigned "id" fields.
    assert gen.start_kwargs["input"]["input"] == wire_body["input"]
    assert all("id" not in item for item in gen.start_kwargs["input"]["input"])


async def test_codex_langfuse_records_rejected_compaction_as_error(monkeypatch) -> None:
    """A transport-successful compaction with no usable item must not trace as a success."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    _mock_codex_token(monkeypatch)
    provider = OpenAICodexProvider(default_model="openai-codex/gpt-5.6-sol")
    state = build_responses_state(
        provider=provider._responses_state_provider(),
        model="gpt-5.6-sol",
        input_items=[{"type": "message", "role": "user", "content": "old question"}],
        output_items=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "old answer"}],
            },
        ],
        usage=provider_base.LLMUsage.reported(input_tokens=90, output_tokens=5, total_tokens=95),
    )
    generations: list[_FakeGeneration] = []

    def start_generation(**kwargs: Any) -> _FakeGeneration:
        gen = _FakeGeneration(kwargs)
        generations.append(gen)
        return gen

    _install_fake_langfuse(monkeypatch, start_generation)

    async def fake_request(
        url, headers, body, verify, proxy=None, on_content_delta=None,
        on_thinking_delta=None, on_tool_call_delta=None,
    ):
        if body["input"][-1].get("type") == "compaction_trigger":
            # HTTP/transport succeeds, but with no usable compaction item -
            # this is the "success" that _call_codex's own validation
            # rejects and falls back on.
            return provider_base.LLMResponse(content=None)
        return provider_base.LLMResponse(content="done")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    response = await provider.chat_with_retry(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "new question"},
        ],
        max_tokens=5,
        provider_context=provider_base.ProviderCallContext(
            conversation_state=state.with_pending_messages([
                {"role": "user", "content": "new question"},
            ]),
            context_window_tokens=100,
        ),
    )

    assert response.content == "done"  # falls back to the uncompacted request
    assert len(generations) == 2
    compaction_gen = generations[0]
    assert compaction_gen.start_kwargs["name"] == "codex_compaction"
    assert compaction_gen.update_calls[-1]["level"] == "ERROR"
    assert compaction_gen.ended is True
