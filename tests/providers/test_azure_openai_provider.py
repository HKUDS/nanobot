"""Test Azure OpenAI provider (Responses API via OpenAI SDK)."""

import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.providers.azure_openai_provider import (
    AzureOpenAIProvider,
    _AzureTokenProvider,
)
from nanobot.providers.base import LLMResponse, ProviderCallContext

# ---------------------------------------------------------------------------
# Init & validation
# ---------------------------------------------------------------------------


def test_init_creates_sdk_client():
    """Provider creates an AsyncOpenAI client with correct base_url."""
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )
    assert provider.api_key == "test-key"
    assert provider.api_base == "https://test-resource.openai.azure.com/"
    assert provider.default_model == "gpt-4o-deployment"
    # SDK client base_url ends with /openai/v1/
    assert str(provider._client.base_url).rstrip("/").endswith("/openai/v1")
    # Static-key path must NOT construct an AAD token provider
    assert provider._token_provider is None


def test_init_base_url_no_trailing_slash():
    """Trailing slashes are normalised before building base_url."""
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://res.openai.azure.com",
    )
    assert str(provider._client.base_url).rstrip("/").endswith("/openai/v1")


def test_init_base_url_with_trailing_slash():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://res.openai.azure.com/",
    )
    assert str(provider._client.base_url).rstrip("/").endswith("/openai/v1")


def test_init_validation_missing_base():
    with pytest.raises(ValueError, match="Azure OpenAI api_base is required"):
        AzureOpenAIProvider(api_key="test", api_base="")


def test_no_api_version_in_base_url():
    """The /openai/v1/ path should NOT contain an api-version query param."""
    provider = AzureOpenAIProvider(api_key="k", api_base="https://res.openai.azure.com")
    base = str(provider._client.base_url)
    assert "api-version" not in base


# ---------------------------------------------------------------------------
# AAD / DefaultAzureCredential fallback
# ---------------------------------------------------------------------------


def _install_fake_azure_identity(monkeypatch, credential_factory):
    """Install a fake ``azure.identity.aio`` module exposing ``DefaultAzureCredential``."""
    azure_mod = sys.modules.get("azure") or SimpleNamespace()
    identity_mod = SimpleNamespace()
    aio_mod = SimpleNamespace(DefaultAzureCredential=credential_factory)
    identity_mod.aio = aio_mod
    azure_mod.identity = identity_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "azure", azure_mod)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_mod)
    monkeypatch.setitem(sys.modules, "azure.identity.aio", aio_mod)


@pytest.fixture
async def azure_wire_requests(monkeypatch):
    """Inject only the HTTP transport; keep the SDK's request/auth path real."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"],
            "output": [{
                "type": "message", "id": f"msg_{len(requests)}",
                "role": "assistant", "status": "completed",
                "content": [{
                    "type": "output_text", "text": f"reply {len(requests)}", "annotations": [],
                }],
            }],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        def create_client(**kwargs):
            return AsyncOpenAI(http_client=http_client, **kwargs)

        monkeypatch.setattr("nanobot.providers.azure_openai_provider.AsyncOpenAI", create_client)
        yield requests


@pytest.mark.asyncio
async def test_aad_token_provider_sends_rotating_bearer_tokens_on_chat_requests(
    monkeypatch, azure_wire_requests,
):
    credential_instance = MagicMock()
    credential_instance.get_token = AsyncMock(side_effect=[
        SimpleNamespace(token="token-A", expires_on=time.time() + 3600),
        SimpleNamespace(token="token-B", expires_on=time.time() + 3600),
    ])
    credential_instance.close = AsyncMock()
    credential_factory = MagicMock(return_value=credential_instance)
    _install_fake_azure_identity(monkeypatch, credential_factory)
    provider = AzureOpenAIProvider(
        api_key="", api_base="https://res.openai.azure.com", default_model="gpt-4o-deployment",
    )
    try:
        responses = [
            await provider.chat([{"role": "user", "content": f"turn {turn}"}])
            for turn in (1, 2)
        ]
    finally:
        await provider.aclose()

    assert [response.content for response in responses] == ["reply 1", "reply 2"]
    assert all(response.finish_reason == "stop" for response in responses)
    assert len(azure_wire_requests) == 2
    assert [request.headers.get("Authorization") for request in azure_wire_requests] == [
        "Bearer token-A", "Bearer token-B",
    ]
    assert all(request.method == "POST" for request in azure_wire_requests)
    assert all(
        str(request.url) == "https://res.openai.azure.com/openai/v1/responses"
        for request in azure_wire_requests
    )
    bodies = [json.loads(request.content) for request in azure_wire_requests]
    assert [body["model"] for body in bodies] == ["gpt-4o-deployment", "gpt-4o-deployment"]
    assert [body["input"][0]["content"][0]["text"] for body in bodies] == ["turn 1", "turn 2"]
    credential_factory.assert_called_once_with()
    assert credential_instance.get_token.await_args_list == [
        call("https://cognitiveservices.azure.com/.default"),
        call("https://cognitiveservices.azure.com/.default"),
    ]


@pytest.mark.asyncio
async def test_explicit_key_sends_bearer_without_constructing_credential(
    monkeypatch, azure_wire_requests,
):
    """Explicit api_key wins through chat(), without invoking Azure credentials."""
    credential_factory = MagicMock(side_effect=AssertionError(
        "DefaultAzureCredential must not be constructed when api_key is set"
    ))
    _install_fake_azure_identity(monkeypatch, credential_factory)
    provider = AzureOpenAIProvider(
        api_key="real-key", api_base="https://res.openai.azure.com",
    )
    try:
        response = await provider.chat([{"role": "user", "content": "hello"}])
    finally:
        await provider.aclose()

    assert response.content == "reply 1"
    assert response.finish_reason == "stop"
    assert len(azure_wire_requests) == 1
    assert azure_wire_requests[0].headers["Authorization"] == "Bearer real-key"
    credential_factory.assert_not_called()


def test_init_missing_key_without_azure_identity_raises(monkeypatch):
    """Clear RuntimeError with install hint when azure-identity is missing."""
    # Force the import inside _AzureTokenProvider to fail.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "azure.identity.aio":
            raise ImportError("No module named 'azure.identity.aio'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match=r"nanobot plugins enable azure"):
            AzureOpenAIProvider(api_key="", api_base="https://res.openai.azure.com")


@pytest.mark.asyncio
async def test_token_provider_returns_credential_token(monkeypatch):
    """Token callback delegates to DefaultAzureCredential.get_token with the AOAI scope."""
    access_token = SimpleNamespace(token="token-A", expires_on=time.time() + 3600)
    credential_instance = MagicMock()
    credential_instance.get_token = AsyncMock(return_value=access_token)

    credential_factory = MagicMock(return_value=credential_instance)
    _install_fake_azure_identity(monkeypatch, credential_factory)

    tp = _AzureTokenProvider()

    assert await tp() == "token-A"
    credential_instance.get_token.assert_awaited_with(
        "https://cognitiveservices.azure.com/.default"
    )
    # No client-side caching layer — every call delegates to the Azure SDK,
    # which has its own MSAL-backed token cache.
    assert await tp() == "token-A"
    assert credential_instance.get_token.await_count == 2


# ---------------------------------------------------------------------------
# _supports_temperature
# ---------------------------------------------------------------------------


def test_supports_temperature_standard_model():
    assert AzureOpenAIProvider._supports_temperature("gpt-4o") is True


def test_supports_temperature_reasoning_model():
    assert AzureOpenAIProvider._supports_temperature("o3-mini") is False
    assert AzureOpenAIProvider._supports_temperature("gpt-5-chat") is False
    assert AzureOpenAIProvider._supports_temperature("o4-mini") is False


def test_supports_temperature_with_reasoning_effort():
    assert AzureOpenAIProvider._supports_temperature("gpt-4o", reasoning_effort="medium") is False


def test_supports_temperature_with_reasoning_effort_none_string():
    """reasoning_effort='none' must NOT suppress temperature — it means thinking is off."""
    assert AzureOpenAIProvider._supports_temperature("gpt-4o", reasoning_effort="none") is True


# ---------------------------------------------------------------------------
# _build_body — Responses API body construction
# ---------------------------------------------------------------------------


def test_build_body_basic():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://res.openai.azure.com", default_model="gpt-4o",
    )
    messages = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "Hi"}]
    body = provider._build_body(messages, None, None, 4096, 0.7, None, None)

    assert body["model"] == "gpt-4o"
    assert body["instructions"] == "You are helpful."
    assert body["temperature"] == 0.7
    assert body["max_output_tokens"] == 4096
    assert body["store"] is False
    assert "reasoning" not in body
    assert "include" not in body
    # input should contain the converted user message only (system extracted)
    assert any(
        item.get("role") == "user"
        for item in body["input"]
    )


def test_build_body_enables_server_compaction():
    provider = AzureOpenAIProvider(
        api_key="k",
        api_base="https://res.openai.azure.com",
        default_model="gpt-5.6",
    )

    body = provider._build_body(
        [{"role": "user", "content": "hello"}],
        None,
        None,
        10_000,
        0.1,
        "high",
        None,
        provider_context=ProviderCallContext(context_window_tokens=200_000),
    )

    assert body["context_management"] == [{
        "type": "compaction",
        "compact_threshold": 180_000,
    }]


def test_build_body_max_tokens_minimum():
    """max_output_tokens should never be less than 1."""
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-4o")
    body = provider._build_body([{"role": "user", "content": "x"}], None, None, 0, 0.7, None, None)
    assert body["max_output_tokens"] == 1


def test_build_body_with_tools():
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-4o")
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    body = provider._build_body(
        [{"role": "user", "content": "weather?"}], tools, None, 4096, 0.7, None, None,
    )
    assert body["tools"] == [{"type": "function", "name": "get_weather", "description": "", "parameters": {}, "strict": False}]
    assert body["tool_choice"] == "auto"


def test_build_body_with_reasoning():
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-5-chat")
    body = provider._build_body(
        [{"role": "user", "content": "think"}], None, "gpt-5-chat", 4096, 0.7, "medium", None,
    )
    assert body["reasoning"] == {"effort": "medium"}
    assert "reasoning.encrypted_content" in body.get("include", [])
    # temperature omitted for reasoning models
    assert "temperature" not in body


def test_build_body_reasoning_effort_none_string_omits_reasoning():
    """reasoning_effort='none' must not inject a reasoning body and must allow temperature."""
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-4o")
    body = provider._build_body(
        [{"role": "user", "content": "hi"}], None, "gpt-4o", 4096, 0.7, "none", None,
    )
    assert "reasoning" not in body
    assert body["temperature"] == 0.7


def test_build_body_image_conversion():
    """image_url content blocks should be converted to input_image."""
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-4o")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "What's in this image?"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ],
    }]
    body = provider._build_body(messages, None, None, 4096, 0.7, None, None)
    user_item = body["input"][0]
    content_types = [b["type"] for b in user_item["content"]]
    assert "input_text" in content_types
    assert "input_image" in content_types
    image_block = next(b for b in user_item["content"] if b["type"] == "input_image")
    assert image_block["image_url"] == "https://example.com/img.png"


def test_build_body_sanitizes_single_dict_content_block():
    """Single content dicts should be preserved via shared message sanitization."""
    provider = AzureOpenAIProvider(api_key="k", api_base="https://r.com", default_model="gpt-4o")
    messages = [{
        "role": "user",
        "content": {"type": "text", "text": "Hi from dict content"},
    }]

    body = provider._build_body(messages, None, None, 4096, 0.7, None, None)

    assert body["input"][0]["content"] == [{"type": "input_text", "text": "Hi from dict content"}]


# ---------------------------------------------------------------------------
# chat() — non-streaming
# ---------------------------------------------------------------------------


def _make_sdk_response(
    content="Hello!", tool_calls=None, status="completed",
    usage=None,
):
    """Build a mock that quacks like an openai Response object."""
    resp = MagicMock()
    resp.model_dump = MagicMock(return_value={
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]},
            *([{
                "type": "function_call",
                "call_id": tc["call_id"], "id": tc["id"],
                "name": tc["name"], "arguments": tc["arguments"],
            } for tc in (tool_calls or [])]),
        ],
        "status": status,
        "usage": {
            "input_tokens": (usage or {}).get("input_tokens", 10),
            "output_tokens": (usage or {}).get("output_tokens", 5),
            "total_tokens": (usage or {}).get("total_tokens", 15),
        },
    })
    return resp


@pytest.mark.asyncio
async def test_chat_success():
    provider = AzureOpenAIProvider(
        api_key="test-key", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )
    mock_resp = _make_sdk_response(content="Hello!")
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(return_value=mock_resp)

    result = await provider.chat([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_chat_retries_without_unsupported_server_compaction():
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test.openai.azure.com",
        default_model="gpt-5.6",
    )

    class UnsupportedCompactionError(Exception):
        status_code = 400
        body = {"error": {"message": "Unknown parameter: context_management"}}

    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(side_effect=[
        UnsupportedCompactionError(),
        _make_sdk_response(content="compaction fallback"),
    ])

    result = await provider.chat(
        [{"role": "user", "content": "Hi"}],
        provider_context=ProviderCallContext(context_window_tokens=200_000),
    )

    create = provider._client.responses.create
    assert result.content == "compaction fallback"
    assert result.provider_state is not None
    assert create.await_count == 2
    assert "context_management" in create.call_args_list[0].kwargs
    assert "context_management" not in create.call_args_list[1].kwargs
    assert provider.supports_native_compaction() is False


@pytest.mark.asyncio
async def test_chat_uses_default_model():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="my-deployment",
    )
    mock_resp = _make_sdk_response(content="ok")
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(return_value=mock_resp)

    await provider.chat([{"role": "user", "content": "test"}])

    call_kwargs = provider._client.responses.create.call_args[1]
    assert call_kwargs["model"] == "my-deployment"


@pytest.mark.asyncio
async def test_chat_custom_model():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )
    mock_resp = _make_sdk_response(content="ok")
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(return_value=mock_resp)

    await provider.chat([{"role": "user", "content": "test"}], model="custom-deploy")

    call_kwargs = provider._client.responses.create.call_args[1]
    assert call_kwargs["model"] == "custom-deploy"


@pytest.mark.asyncio
async def test_chat_with_tool_calls():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )
    mock_resp = _make_sdk_response(
        content=None,
        tool_calls=[{
            "call_id": "call_123", "id": "fc_1",
            "name": "get_weather", "arguments": '{"location": "SF"}',
        }],
    )
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(return_value=mock_resp)

    result = await provider.chat(
        [{"role": "user", "content": "Weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == {"location": "SF"}
    assert result.provider_state is not None


@pytest.mark.asyncio
async def test_chat_error_handling():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(side_effect=Exception("Connection failed"))

    result = await provider.chat([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert "Connection failed" in result.content
    assert result.finish_reason == "error"


@pytest.mark.asyncio
async def test_chat_reasoning_param_format():
    """reasoning_effort should be sent as reasoning={effort: ...} not a flat string."""
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-5-chat",
    )
    mock_resp = _make_sdk_response(content="thought")
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(return_value=mock_resp)

    await provider.chat(
        [{"role": "user", "content": "think"}], reasoning_effort="medium",
    )

    call_kwargs = provider._client.responses.create.call_args[1]
    assert call_kwargs["reasoning"] == {"effort": "medium"}
    assert "reasoning_effort" not in call_kwargs


# ---------------------------------------------------------------------------
# chat_stream()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_success():
    """Streaming should call on_content_delta and return combined response."""
    provider = AzureOpenAIProvider(
        api_key="test-key", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )

    # Build mock SDK stream events
    events = []
    ev1 = MagicMock(type="response.output_text.delta", delta="Hello")
    ev2 = MagicMock(type="response.output_text.delta", delta=" world")
    resp_obj = MagicMock(status="completed")
    ev3 = MagicMock(type="response.completed", response=resp_obj)
    events = [ev1, ev2, ev3]

    async def mock_stream():
        for e in events:
            yield e

    provider._client.responses = MagicMock()
    stream = MagicMock()
    stream.__aiter__.side_effect = mock_stream
    provider._client.responses.create = AsyncMock(return_value=stream)

    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    result = await provider.chat_stream(
        [{"role": "user", "content": "Hi"}], on_content_delta=on_delta,
    )

    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert deltas == ["Hello", " world"]
    stream.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_stream_with_tool_calls():
    """Streaming tool calls should be accumulated correctly."""
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )

    item_added = MagicMock(type="function_call", call_id="call_1", id="fc_1", arguments="")
    item_added.name = "get_weather"
    ev_added = MagicMock(type="response.output_item.added", item=item_added)
    ev_args_delta = MagicMock(type="response.function_call_arguments.delta", call_id="call_1", delta='{"loc')
    ev_args_done = MagicMock(
        type="response.function_call_arguments.done",
        call_id="call_1", arguments='{"location":"SF"}',
    )
    item_done = MagicMock(
        type="function_call", call_id="call_1", id="fc_1",
        arguments='{"location":"SF"}',
    )
    item_done.name = "get_weather"
    ev_item_done = MagicMock(type="response.output_item.done", item=item_done)
    resp_obj = MagicMock(status="completed")
    resp_obj.model_dump.return_value = {"status": "completed", "output": []}
    ev_completed = MagicMock(type="response.completed", response=resp_obj)

    async def mock_stream():
        for e in [ev_added, ev_args_delta, ev_args_done, ev_item_done, ev_completed]:
            yield e

    provider._client.responses = MagicMock()
    stream = MagicMock()
    stream.__aiter__.side_effect = mock_stream
    provider._client.responses.create = AsyncMock(return_value=stream)

    result = await provider.chat_stream(
        [{"role": "user", "content": "weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == {"location": "SF"}
    assert result.provider_state is not None


@pytest.mark.asyncio
async def test_chat_stream_error():
    """Streaming should return error when SDK raises."""
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://test.openai.azure.com", default_model="gpt-4o",
    )
    provider._client.responses = MagicMock()
    provider._client.responses.create = AsyncMock(side_effect=Exception("Connection failed"))

    result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert "Connection failed" in result.content
    assert result.finish_reason == "error"


# ---------------------------------------------------------------------------
# get_default_model
# ---------------------------------------------------------------------------


def test_get_default_model():
    provider = AzureOpenAIProvider(
        api_key="k", api_base="https://r.com", default_model="my-deploy",
    )
    assert provider.get_default_model() == "my-deploy"
