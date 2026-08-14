"""Tests for the DashScope native-protocol provider."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nanobot.config.schema import Config
from nanobot.providers.dashscope_provider import DashScopeProvider
from nanobot.providers.factory import make_provider
from nanobot.providers.registry import find_by_name

# ---------------------------------------------------------------------------
# Registry / config wiring
# ---------------------------------------------------------------------------


def test_dashscope_native_registry_spec() -> None:
    spec = find_by_name("dashscope_native")
    assert spec is not None
    assert spec.backend == "dashscope_native"
    assert spec.env_key == "DASHSCOPE_API_KEY"
    assert spec.default_api_base == "https://dashscope.aliyuncs.com"
    assert spec.model_catalog == "builtin"
    model_ids = [m.id for m in spec.builtin_models]
    assert "qwen3.8-max" in model_ids
    assert "qwen-plus" in model_ids


def test_dashscope_native_config_field_and_provider_resolution() -> None:
    cfg = Config.model_validate({
        "providers": {"dashscope_native": {"apiKey": "sk-test"}},
        "modelPresets": {
            "main": {"model": "qwen3.8-max", "provider": "dashscope_native"},
        },
    })
    assert cfg.get_provider_name("qwen3.8-max") == "dashscope_native"
    provider = make_provider(cfg, preset=cfg.model_presets["main"])
    assert isinstance(provider, DashScopeProvider)
    assert provider.get_default_model() == "qwen3.8-max"


def test_qwen_models_still_match_compatible_spec() -> None:
    """Keyword matching for qwen* model names must keep resolving to the
    OpenAI-compatible dashscope provider, not the native one."""
    cfg = Config.model_validate({
        "providers": {"dashscope": {"apiKey": "sk-test"}},
    })
    assert cfg.get_provider_name("qwen3.7-plus") == "dashscope"


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


def test_convert_messages_text_only() -> None:
    messages = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "f", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "42"},
    ]
    converted, multimodal = DashScopeProvider._convert_messages(messages)
    assert multimodal is False
    assert converted == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "f", "arguments": "{}"},
            }],
        },
        {"role": "tool", "content": "42", "tool_call_id": "call_1"},
    ]


def test_convert_user_content_image_blocks() -> None:
    content = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}},
        {"type": "text", "text": "what is this?"},
        {"_meta": {"path": "/tmp/a.png"}},
    ]
    converted, multimodal = DashScopeProvider._convert_user_content(content)
    assert multimodal is True
    assert converted == [
        {"image": "data:image/png;base64,xyz"},
        {"text": "what is this?"},
    ]


def test_convert_user_content_text_only_list_stays_string() -> None:
    converted, multimodal = DashScopeProvider._convert_user_content(
        [{"type": "text", "text": "plain"}]
    )
    assert multimodal is False
    assert converted == "plain"


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


def _provider() -> DashScopeProvider:
    return DashScopeProvider(api_key="sk-test", default_model="qwen-plus")


def test_build_payload_places_tools_in_parameters() -> None:
    tools = [{
        "type": "function",
        "function": {"name": "f", "description": "d", "parameters": {}},
    }]
    payload, path = _provider()._build_payload(
        [{"role": "user", "content": "hi"}],
        tools,
        "qwen3.8-max",
        1024,
        0.5,
        None,
        "auto",
        stream=False,
    )
    assert path == "/api/v1/services/aigc/text-generation/generation"
    assert payload["model"] == "qwen3.8-max"
    assert payload["parameters"]["result_format"] == "message"
    assert payload["parameters"]["max_tokens"] == 1024
    assert payload["parameters"]["temperature"] == 0.5
    assert payload["parameters"]["tools"] == tools
    assert "tool_choice" not in payload["parameters"]
    assert "incremental_output" not in payload["parameters"]


def test_build_payload_stream_and_tool_choice() -> None:
    payload, _ = _provider()._build_payload(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "f", "parameters": {}}}],
        None,
        64,
        0.1,
        None,
        "required",
        stream=True,
    )
    assert payload["model"] == "qwen-plus"  # default model fallback
    assert payload["parameters"]["incremental_output"] is True
    assert payload["parameters"]["tool_choice"] == "required"


def test_build_payload_multimodal_routing_and_thinking() -> None:
    payload, path = _provider()._build_payload(
        [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
                {"type": "text", "text": "describe"},
            ],
        }],
        None,
        "qwen3.8-max",
        512,
        0.7,
        "medium",
        None,
        stream=False,
    )
    assert path == "/api/v1/services/aigc/multimodal-generation/generation"
    assert payload["parameters"]["enable_thinking"] is True
    assert payload["parameters"]["reasoning_effort"] == "medium"
    assert payload["input"]["messages"][0]["content"][0] == {"image": "https://x/y.png"}


def test_build_payload_merges_extra_body() -> None:
    provider = DashScopeProvider(
        api_key="sk-test",
        extra_body={"top_k": 20},
    )
    payload, _ = provider._build_payload(
        [{"role": "user", "content": "hi"}],
        None,
        None,
        64,
        0.1,
        None,
        None,
        stream=False,
    )
    assert payload["parameters"]["top_k"] == 20


# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, data: dict[str, Any] | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text or (json.dumps(self._data) if data else "")

    def json(self) -> dict[str, Any]:
        return self._data


class FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str], error_text: str = ""):
        self.status_code = status_code
        self._lines = lines
        self._error_text = error_text

    async def aread(self) -> bytes:
        return self._error_text.encode()

    def aiter_lines(self):
        async def _gen():
            for line in self._lines:
                yield line
        return _gen()


class FakeStreamContext:
    def __init__(self, response: FakeStreamResponse):
        self.response = response

    async def __aenter__(self) -> FakeStreamResponse:
        return self.response

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeClient:
    def __init__(
        self,
        post_response: FakeResponse | None = None,
        stream_response: FakeStreamResponse | None = None,
    ):
        self.post_response = post_response
        self.stream_response = stream_response
        self.post_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"path": path, **kwargs})
        assert self.post_response is not None
        return self.post_response

    def stream(self, method: str, path: str, **kwargs: Any) -> FakeStreamContext:
        self.stream_calls.append({"method": method, "path": path, **kwargs})
        assert self.stream_response is not None
        return FakeStreamContext(self.stream_response)


# ---------------------------------------------------------------------------
# chat() non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_parses_content_usage_and_tool_calls() -> None:
    fake = FakeClient(post_response=FakeResponse(200, {
        "request_id": "r1",
        "output": {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "index": 0,
                        "function": {
                            "name": "get_weather",
                            "arguments": "{\"city\": \"Beijing\"}",
                        },
                    }],
                },
            }],
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        },
    }))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    response = await provider.chat(
        [{"role": "user", "content": "weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
    )

    assert response.finish_reason == "tool_calls"
    assert response.has_tool_calls
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"city": "Beijing"}
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    # tools must ride in `parameters`, not `input`
    body = fake.post_calls[0]["json"]
    assert body["parameters"]["tools"][0]["function"]["name"] == "get_weather"
    assert "tools" not in body["input"]


@pytest.mark.asyncio
async def test_chat_reasoning_and_array_content() -> None:
    fake = FakeClient(post_response=FakeResponse(200, {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [{"text": "你好"}, {"text": "世界"}],
                    "reasoning_content": "let me think",
                },
            }],
            "usage": {},
        },
    }))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.content == "你好世界"
    assert response.reasoning_content == "let me think"


@pytest.mark.asyncio
async def test_chat_http_error_sets_retry_metadata() -> None:
    fake = FakeClient(post_response=FakeResponse(
        429,
        text=json.dumps({"code": "Throttling.RateQuota", "message": "Requests rate exceeded"}),
    ))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert response.error_status_code == 429
    assert response.error_code == "throttling.ratequota"
    assert response.error_should_retry is True


@pytest.mark.asyncio
async def test_chat_logical_error_with_http_200() -> None:
    fake = FakeClient(post_response=FakeResponse(200, {
        "code": "InvalidApiKey",
        "message": "Invalid API-key provided.",
        "request_id": "r9",
    }))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert response.error_code == "invalidapikey"
    assert response.error_should_retry is False


@pytest.mark.asyncio
async def test_chat_requires_api_key() -> None:
    provider = DashScopeProvider(api_key=None)
    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert "API key" in (response.content or "")


# ---------------------------------------------------------------------------
# chat_stream() streaming
# ---------------------------------------------------------------------------


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}"


@pytest.mark.asyncio
async def test_chat_stream_content_and_reasoning_deltas() -> None:
    lines = [
        _sse({"output": {"choices": [{
            "finish_reason": "null",
            "message": {"content": "Hel", "reasoning_content": "th"},
        }]}}),
        ": keep-alive comment",
        _sse({"output": {"choices": [{
            "finish_reason": "null",
            "message": {"content": "lo"},
        }]}}),
        _sse({"output": {
            "choices": [{"finish_reason": "stop", "message": {}}],
            "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
        }}),
    ]
    fake = FakeClient(stream_response=FakeStreamResponse(200, lines))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    content_deltas: list[str] = []
    thinking_deltas: list[str] = []

    async def on_content(text: str) -> None:
        content_deltas.append(text)

    async def on_thinking(text: str) -> None:
        thinking_deltas.append(text)

    response = await provider.chat_stream(
        [{"role": "user", "content": "hi"}],
        on_content_delta=on_content,
        on_thinking_delta=on_thinking,
    )

    assert content_deltas == ["Hel", "lo"]
    assert thinking_deltas == ["th"]
    assert response.content == "Hello"
    assert response.reasoning_content == "th"
    assert response.finish_reason == "stop"
    assert response.usage["prompt_tokens"] == 7

    stream_call = fake.stream_calls[0]
    assert stream_call["path"] == "/api/v1/services/aigc/text-generation/generation"
    assert stream_call["headers"]["X-DashScope-SSE"] == "enable"
    assert stream_call["json"]["parameters"]["incremental_output"] is True


@pytest.mark.asyncio
async def test_chat_stream_tool_call_accumulation() -> None:
    lines = [
        _sse({"output": {"choices": [{
            "finish_reason": "null",
            "message": {"tool_calls": [{
                "index": 0,
                "id": "call_1",
                "function": {"name": "get_weather", "arguments": "{\"city\":"},
            }]},
        }]}}),
        _sse({"output": {"choices": [{
            "finish_reason": "null",
            "message": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": " \"Beijing\"}"},
            }]},
        }]}}),
        _sse({"output": {
            "choices": [{"finish_reason": "tool_calls", "message": {}}],
            "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        }}),
    ]
    fake = FakeClient(stream_response=FakeStreamResponse(200, lines))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    tool_deltas: list[dict[str, Any]] = []

    async def on_tool_delta(delta: dict[str, Any]) -> None:
        tool_deltas.append(delta)

    response = await provider.chat_stream(
        [{"role": "user", "content": "weather?"}],
        on_tool_call_delta=on_tool_delta,
    )

    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"city": "Beijing"}
    assert tool_deltas[0]["name"] == "get_weather"
    assert tool_deltas[1]["arguments_delta"] == ' "Beijing"}'


@pytest.mark.asyncio
async def test_chat_stream_http_error() -> None:
    fake = FakeClient(stream_response=FakeStreamResponse(
        401,
        [],
        error_text=json.dumps({"code": "InvalidApiKey", "message": "bad key"}),
    ))
    provider = DashScopeProvider(api_key="sk-test", client=fake)

    response = await provider.chat_stream([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert response.error_status_code == 401
    assert response.error_should_retry is False
