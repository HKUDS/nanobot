"""Input attribution at the real provider serialization/dispatch boundary."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.input_usage import InputSnapshot, InputUsage
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def chat_response(tokens=9000, *, tool=False):
    calls = [SimpleNamespace(
        id="call-1", index=0, type="function",
        function=SimpleNamespace(name="lookup", arguments="{}"),
    )] if tool else None
    message = SimpleNamespace(content="done" if not tool else "checking", tool_calls=calls)
    usage = SimpleNamespace(prompt_tokens=tokens, completion_tokens=5, total_tokens=tokens + 5)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if tool else "stop")],
        usage=usage,
    )


def chat_stream(tokens=9000, *, tool=False):
    response = chat_response(tokens, tool=tool)

    async def chunks():
        yield SimpleNamespace(
            choices=[SimpleNamespace(
                delta=response.choices[0].message,
                finish_reason=response.choices[0].finish_reason,
            )], usage=None,
        )
        yield SimpleNamespace(choices=[], usage=response.usage)
    return chunks()


def provider_client(monkeypatch, *, responses=None):
    provider = OpenAICompatProvider(
        provider_name="openrouter", default_model="xiaomi/mimo-v2.5",
        spec=find_by_name("openrouter"), api_key="test-only",
    )
    create = AsyncMock(side_effect=responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(provider, "_ensure_client", AsyncMock(return_value=client))
    return provider, create, client


@pytest.mark.parametrize("stream", [False, True])
async def test_receipt_matches_actual_chat_payload(monkeypatch, stream):
    provider, create, _ = provider_client(monkeypatch)
    create.return_value = chat_stream() if stream else chat_response()
    messages = [{"role": "user", "content": "中文 with source metadata", "timestamp": "private"}]
    kwargs = dict(max_tokens=1000, temperature=0.7, reasoning_effort=None)
    predicted = provider.input_snapshot(messages, [], "xiaomi/mimo-v2.5", **kwargs)
    call = provider.chat_stream if stream else provider.chat
    response = await call(messages, [], "xiaomi/mimo-v2.5", **kwargs)
    assert response.input_snapshot == predicted
    assert response.usage.input_tokens == 9000
    # Provider filtering, not raw canonical history, defines the measured prefix.
    assert "timestamp" not in create.call_args.kwargs["messages"][0]
    assert "timestamp" in messages[0]


@pytest.mark.parametrize("change", ["append", "rewrite", "reorder", "tools", "model", "options", "scope"])
def test_measurement_only_matches_exact_append_only_contract(change):
    body = {"model": "one", "messages": [
        {"role": "system", "content": "stable"}, {"role": "user", "content": "hello"},
    ], "tools": [{"name": "lookup"}], "reasoning_effort": "low"}
    usage = InputUsage(InputSnapshot.from_chat_request("scope-1", body), 9000)
    candidate = deepcopy(body)
    scope = "scope-1"
    if change == "append":
        candidate["messages"].append({"role": "assistant", "content": "answer"})
    elif change == "rewrite":
        candidate["messages"][0]["content"] = "summary"
    elif change == "reorder":
        candidate["messages"].reverse()
    elif change == "tools":
        candidate["tools"] = []
    elif change == "model":
        candidate["model"] = "two"
    elif change == "options":
        candidate["reasoning_effort"] = "high"
    elif change == "scope":
        scope = "scope-2"
    floor = usage.floor_for(InputSnapshot.from_chat_request(scope, candidate))
    assert floor == (9000 if change == "append" else None)


async def test_fallback_receipt_is_never_relabelled_as_primary(monkeypatch):
    primary, primary_create, _ = provider_client(monkeypatch)
    primary_create.side_effect = TimeoutError("timed out")
    fallback, fallback_create, _ = provider_client(monkeypatch)
    fallback_create.return_value = chat_response()
    preset = ModelPresetConfig(
        model="xiaomi/mimo-v2.5", provider="openrouter", max_tokens=1000, temperature=0.7,
    )
    wrapper = FallbackProvider(primary, [preset], lambda _preset: fallback)
    messages = [{"role": "user", "content": "hello"}]
    kwargs = dict(max_tokens=1000, temperature=0.7, reasoning_effort=None)
    expected_primary = wrapper.input_snapshot(messages, [], preset.model, **kwargs)
    response = await wrapper.chat(messages=messages, tools=[], model=preset.model, **kwargs)
    assert response.input_snapshot is not None
    assert response.input_snapshot != expected_primary
    assert InputUsage(response.input_snapshot, 9000).floor_for(expected_primary) is None
    assert primary_create.await_count == fallback_create.await_count == 1


async def test_responses_to_chat_fallback_does_not_claim_responses_identity(monkeypatch):
    provider, create, client = provider_client(monkeypatch)
    create.return_value = chat_response()
    client.responses = SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("unsupported")))
    monkeypatch.setattr(provider, "_should_use_responses_api", lambda *_args: True)
    monkeypatch.setattr(provider, "_should_fallback_from_responses_error", lambda _error: True)
    messages = [{"role": "user", "content": "hello"}]
    kwargs = dict(max_tokens=1000, temperature=0.7, reasoning_effort=None)
    assert provider.input_snapshot(messages, [], provider.default_model, **kwargs) is None
    response = await provider.chat(messages, [], provider.default_model, **kwargs)
    assert response.input_snapshot is not None
    assert provider.input_snapshot(messages, [], provider.default_model, **kwargs) is None
    monkeypatch.setattr(provider, "_should_use_responses_api", lambda *_args: False)
    assert provider.input_snapshot(messages, [], provider.default_model, **kwargs) == response.input_snapshot


async def test_retry_receipt_belongs_to_successful_physical_request(monkeypatch):
    provider, create, _ = provider_client(monkeypatch, responses=[
        TimeoutError("timed out"), chat_stream(1234),
    ])
    monkeypatch.setattr(provider, "_CHAT_RETRY_DELAYS", (0,))
    messages = [{"role": "user", "content": "retry unchanged"}]
    kwargs = dict(max_tokens=1000, temperature=0.7, reasoning_effort=None)
    response = await provider.chat_stream_with_retry(
        messages=messages, tools=[], model=provider.default_model, **kwargs,
    )
    assert create.await_count == 2
    assert response.usage.input_tokens == 1234
    assert response.usage.request_count == 1
    assert response.input_snapshot == provider.input_snapshot(
        messages, [], provider.default_model, **kwargs,
    )
