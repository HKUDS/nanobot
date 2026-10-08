"""Preset API declarations control requests through OpenAI-compatible gateways."""

import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from nanobot.config.schema import Config, InlineFallbackConfig, ModelAPIConfig, ModelPresetConfig
from nanobot.providers.factory import make_provider, provider_signature, validate_provider_setup
from nanobot.providers.openai_compat_provider import _RESPONSES_FAILURE_THRESHOLD


def _config() -> Config:
    return Config.model_validate({
        "agents": {"defaults": {"modelPreset": "responses"}},
        "providers": {"tenant": {"apiBase": "https://tenant.test/v1", "apiKey": "fixture"}},
        "modelPresets": {
            "responses": {
                "provider": "tenant", "model": "gpt-6-luna", "reasoningEffort": "high",
                "api": {"supportedApis": ["responses"], "preferredApi": "responses"},
            },
            "chat": {
                "provider": "tenant", "model": "gpt-6-luna",
                "api": {"supportedApis": ["chat_completions"]},
            },
        },
    })


def _answer(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/responses"):
        response = {
            "id": "resp_fixture", "object": "response", "status": "completed",
            "output": [{
                "id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }],
        }
        events = [
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": response},
        ]
    else:
        response = {"id": "chat_fixture", "choices": [{
            "index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop",
        }]}
        events = [{"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}]}]
    if not json.loads(request.content).get("stream"):
        return httpx.Response(200, json=response)
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


@pytest.fixture
async def bind_transport():
    clients = []

    def bind(provider, handler):
        original = provider._client
        if original is not None:
            clients.append(original)
        client = AsyncOpenAI(
            api_key="fixture", base_url="https://tenant.test/v1", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        provider._client = client
        provider._CHAT_RETRY_DELAYS = ()
        return provider

    yield bind
    for client in clients:
        await client.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_two_presets_route_same_gateway_model_independently(bind_transport, stream):
    config = _config()
    requests = []

    def handler(request):
        requests.append(request)
        return _answer(request)

    tools = [{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}},
    }}]
    for name in ("responses", "chat"):
        provider = bind_transport(make_provider(config, preset_name=name), handler)
        invoke = provider.chat_stream if stream else provider.chat
        result = await invoke(
            [{"role": "user", "content": "hello"}], tools=tools,
            reasoning_effort=provider.generation.reasoning_effort,
        )
        assert result.content == "ok"
    assert [request.url.path for request in requests] == ["/v1/responses", "/v1/chat/completions"]
    body = json.loads(requests[0].content)
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"][0]["name"] == "lookup"
    assert "context_management" not in body
    assert "include" not in body


@pytest.mark.parametrize("allow_chat", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_compatibility_fallback_requires_preset_support(bind_transport, allow_chat, stream):
    config = _config()
    if allow_chat:
        config.model_presets["responses"].api = ModelAPIConfig(
            supported_apis=("responses", "chat_completions"), preferred_api="responses",
        )
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/responses"):
            return httpx.Response(404, json={"error": {"message": "Responses endpoint not supported", "type": "invalid_request_error"}})
        return _answer(request)

    provider = bind_transport(make_provider(config), handler)
    invoke = provider.chat_stream if stream else provider.chat
    for _ in range(_RESPONSES_FAILURE_THRESHOLD + 1):
        result = await invoke([{"role": "user", "content": "hello"}])
        assert result.finish_reason == ("stop" if allow_chat else "error")
    if allow_chat:
        assert requests == ["/v1/responses", "/v1/chat/completions"] * _RESPONSES_FAILURE_THRESHOLD + ["/v1/chat/completions"]
    else:
        assert requests == ["/v1/responses"] * (_RESPONSES_FAILURE_THRESHOLD + 1)


@pytest.mark.parametrize("inline", [False, True])
async def test_fallback_preset_keeps_its_api_and_invalidates_runtime(bind_transport, monkeypatch, inline):
    config = _config()
    fallback = config.model_presets["chat"]
    config.agents.defaults.fallback_models = [
        InlineFallbackConfig.model_validate(fallback.model_dump()) if inline else "chat",
    ]
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/responses"):
            return httpx.Response(401, json={"error": {"message": "invalid_api_key", "type": "authentication_error"}})
        return _answer(request)

    from nanobot.providers import factory

    original = factory._make_provider_core
    monkeypatch.setattr(factory, "_make_provider_core", lambda *args, **kwargs: bind_transport(original(*args, **kwargs), handler))
    provider = make_provider(config)
    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert result.content == "ok"
    assert requests == ["/v1/responses", "/v1/chat/completions"]
    previous = provider_signature(config)
    candidate = config.agents.defaults.fallback_models[0] if inline else config.model_presets["chat"]
    candidate.api = ModelAPIConfig(supported_apis=("responses",))
    assert provider_signature(config) != previous
    config.agents.defaults.fallback_models = []
    previous = provider_signature(config)
    config.model_presets["responses"].api = None
    assert provider_signature(config) != previous


def test_preset_api_preference_must_be_supported():
    with pytest.raises(ValidationError, match="preferred_api must be one of supported_apis"):
        ModelAPIConfig.model_validate({"supportedApis": ["chat_completions"], "preferredApi": "responses"})


def test_fixed_provider_validates_preset_api_before_loading_client():
    config = Config()
    preset = ModelPresetConfig(
        provider="openai_codex", model="gpt-6-astra", api=ModelAPIConfig(supported_apis=("responses",)),
    )
    validate_provider_setup(config, preset=preset)
    preset.api = ModelAPIConfig(supported_apis=("responses", "chat_completions"))
    with pytest.raises(ValueError, match="OpenAI Codex.*does not support chat_completions"):
        validate_provider_setup(config, preset=preset)


@pytest.mark.parametrize("apis,preferred", [
    (("responses",), "responses"),
    (("chat_completions",), "chat_completions"),
    (("chat_completions", "responses"), "chat_completions"),
])
async def test_preset_overrides_legacy_openai_default_and_scopes_compaction(bind_transport, apis, preferred):
    config = _config()
    preset = config.model_presets["responses"]
    preset.provider = "openai"
    preset.api = ModelAPIConfig(supported_apis=apis, preferred_api=preferred)
    config.providers.openai.api_key = "fixture"
    config.providers.openai.api_type = "chat_completions"
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return _answer(request)

    provider = bind_transport(make_provider(config), handler)
    assert provider.supports_native_compaction() is (preferred == "responses")
    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert result.content == "ok"
    assert requests == ["/v1/responses" if preferred == "responses" else "/v1/chat/completions"]
