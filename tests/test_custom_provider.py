import json
from types import SimpleNamespace

import pytest

from nanobot.providers.custom_provider import CustomLLMConfig, CustomLLMProvider


class DummyFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class DummyToolCall:
    def __init__(self, tool_id, name, arguments):
        self.id = tool_id
        self.function = DummyFunction(name, arguments)


class DummyMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class DummyChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class DummyResponse:
    def __init__(self, message, usage=None):
        self.choices = [DummyChoice(message)]
        self.usage = usage


def _make_provider(**overrides):
    config = CustomLLMConfig(**overrides)
    return CustomLLMProvider(config)


def test_config_validation_rejects_negative_limit():
    with pytest.raises(ValueError):
        CustomLLMConfig(total_tokens_limit=-1)


def test_config_validation_rejects_invalid_headers():
    with pytest.raises(ValueError):
        CustomLLMProvider(CustomLLMConfig(headers={"": "x"}))
    with pytest.raises(ValueError):
        CustomLLMProvider(CustomLLMConfig(headers={"X-Test": 1}))


@pytest.mark.asyncio
async def test_custom_headers_and_validator(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return DummyResponse(DummyMessage("ok"))

    def validator(context):
        captured["validator_context"] = context
        return True

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = _make_provider(
        default_model="openai/gpt-4o",
        headers={"X-Test": "1"},
        api_validator=validator,
    )
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert captured["headers"] == {"X-Test": "1"}
    assert captured["validator_context"]["headers"] == {"X-Test": "1"}


@pytest.mark.asyncio
async def test_api_validator_fail_short_circuit(monkeypatch):
    async def fake_acompletion(**kwargs):
        raise AssertionError("acompletion should not be called")

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = _make_provider(
        default_model="openai/gpt-4o",
        api_validator=lambda context: False,
    )
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert response.content == "API validation failed"


@pytest.mark.asyncio
async def test_response_size_bytes_with_tool_calls(monkeypatch):
    tool_call = DummyToolCall("1", "tool", {"a": 1})
    message = DummyMessage("ok", tool_calls=[tool_call])
    response = DummyResponse(message)

    async def fake_acompletion(**kwargs):
        return response

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = _make_provider(default_model="openai/gpt-4o")
    parsed = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    expected = len("ok".encode("utf-8"))
    payload = [{"id": "1", "name": "tool", "arguments": {"a": 1}}]
    expected += len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    assert parsed.response_size_bytes == expected


@pytest.mark.asyncio
async def test_total_tokens_limit_precheck_blocks(monkeypatch):
    async def fake_acompletion(**kwargs):
        raise AssertionError("acompletion should not be called")

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = _make_provider(
        default_model="openai/gpt-4o",
        total_tokens_limit=10,
        enforce_total_tokens_precheck=True,
    )
    provider.total_tokens_used = 5
    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=6,
    )

    assert response.finish_reason == "error"
    assert "exceeds limit" in response.content


@pytest.mark.asyncio
async def test_total_tokens_limit_postcheck_blocks(monkeypatch):
    usage = SimpleNamespace(
        prompt_tokens=1,
        completion_tokens=5,
        total_tokens=5,
    )
    message = DummyMessage("ok")
    response = DummyResponse(message, usage=usage)

    async def fake_acompletion(**kwargs):
        return response

    monkeypatch.setattr(
        "nanobot.providers.custom_provider.acompletion",
        fake_acompletion,
    )

    provider = _make_provider(
        default_model="openai/gpt-4o",
        total_tokens_limit=10,
        enforce_total_tokens_postcheck=True,
    )
    provider.total_tokens_used = 6
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert provider.is_token_limit_blocked is True
