"""Preset API declarations control requests through OpenAI-compatible gateways."""

import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import ValidationError

from nanobot.config.schema import (
    Config,
    InlineFallbackConfig,
    ModelAPIConfig,
    ModelPresetConfig,
    ProviderAPIConfig,
)
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.factory import (
    make_provider,
    provider_signature,
    resolve_automatic_model_api,
    validate_provider_setup,
)
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
            "messages": {
                "provider": "tenant", "model": "tenant/claude-sonnet-4-6",
                "reasoningEffort": "high",
                "api": {"supportedApis": ["anthropic_messages"]},
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
    elif request.url.path.endswith("/messages"):
        response = {
            "id": "msg_fixture", "type": "message", "role": "assistant",
            "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
        events = [
            {"type": "message_start", "message": {**response, "content": [], "stop_reason": None}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}},
            {"type": "message_stop"},
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
        content="".join(f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n" for event in events),
    )


@pytest.fixture
async def bind_transport():
    clients = []

    def bind(provider, handler):
        original = provider._client
        if original is not None:
            clients.append(original)
        client_type = AsyncAnthropic if isinstance(provider, AnthropicProvider) else AsyncOpenAI
        client = client_type(
            api_key="fixture", base_url=str(original.base_url) if original else "https://tenant.test/v1",
            default_headers=original.default_headers if original else None,
            default_query=original.default_query if original else None,
            max_retries=0,
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
@pytest.mark.parametrize(("provider_name", "model", "api_base", "effort"), [
    ("tenant", "gpt-6-luna", "https://tenant.test/v1", "high"),
    ("openai", "openai/gpt-6-luna", "https://api.openai.com/v1", None),
    ("openai", "gpt-6-luna", "https://tenant.test/v1", "high"),
    ("openai", "gpt-4o", "https://api.openai.com/v1", "high"),
    ("opencode_go", "opencode-go/muse-spark-1.3-contributor", "https://opencode.ai/zen/go/v1", None),
])
async def test_automatic_preview_matches_actual_request(
    bind_transport, stream, provider_name, model, api_base, effort,
):
    config = Config.model_validate({
        "providers": {provider_name: {"apiBase": api_base, "apiKey": "fixture"}},
    })
    preset = ModelPresetConfig(model=model, provider=provider_name, reasoning_effort=effort)
    resolved_provider, api = resolve_automatic_model_api(config, preset=preset)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return _answer(request)

    provider = bind_transport(make_provider(config, preset=preset), handler)
    invoke = provider.chat_stream if stream else provider.chat
    response = await invoke([{"role": "user", "content": "hello"}], reasoning_effort=effort)
    assert response.content == "ok"
    assert resolved_provider == provider_name
    assert paths == ["/v1/responses" if api == "responses" else "/v1/chat/completions"]


@pytest.mark.parametrize("stream", [False, True])
async def test_presets_route_same_gateway_independently(bind_transport, stream):
    config = _config()
    requests = []

    def handler(request):
        requests.append(request)
        return _answer(request)

    tools = [{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}},
    }}]
    for name in ("responses", "chat", "messages"):
        provider = bind_transport(make_provider(config, preset_name=name), handler)
        invoke = provider.chat_stream if stream else provider.chat
        result = await invoke(
            [{"role": "user", "content": "hello"}], tools=tools,
            reasoning_effort=provider.generation.reasoning_effort,
        )
        assert result.content == "ok"
    assert [request.url.path for request in requests] == [
        "/v1/responses", "/v1/chat/completions", "/v1/messages",
    ]
    body = json.loads(requests[0].content)
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"][0]["name"] == "lookup"
    assert "context_management" not in body
    assert "include" not in body
    messages_body = json.loads(requests[2].content)
    assert messages_body["model"] == "claude-sonnet-4-6"
    assert messages_body["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert messages_body["tools"][0]["name"] == "lookup"
    assert messages_body["tools"][0]["input_schema"] == tools[0]["function"]["parameters"]


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
@pytest.mark.parametrize("fallback_name", ["chat", "messages"])
async def test_fallback_preset_keeps_its_api_and_invalidates_runtime(bind_transport, monkeypatch, inline, fallback_name):
    config = _config()
    fallback = config.model_presets[fallback_name]
    config.agents.defaults.fallback_models = [
        InlineFallbackConfig.model_validate(fallback.model_dump()) if inline else fallback_name,
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
    assert requests == ["/v1/responses", "/v1/messages" if fallback_name == "messages" else "/v1/chat/completions"]
    previous = provider_signature(config)
    candidate = config.agents.defaults.fallback_models[0] if inline else fallback
    candidate.api = ModelAPIConfig(supported_apis=("responses",))
    assert provider_signature(config) != previous
    config.agents.defaults.fallback_models = []
    previous = provider_signature(config)
    config.model_presets["responses"].api = None
    assert provider_signature(config) != previous


def test_preset_api_preference_must_be_supported():
    with pytest.raises(ValidationError, match="preferred_api must be one of supported_apis"):
        ModelAPIConfig.model_validate({"supportedApis": ["chat_completions"], "preferredApi": "responses"})


@pytest.mark.parametrize("other_api", ["responses", "chat_completions"])
def test_messages_rejects_cross_protocol_fallback(other_api):
    with pytest.raises(ValidationError, match="cannot be combined"):
        ModelAPIConfig(supported_apis=("anthropic_messages", other_api))


@pytest.mark.parametrize("provider_name", ["tenant", "custom", "anthropic", "openai"])
async def test_messages_declaration_validates_adapter_before_loading_client(provider_name):
    config = _config()
    config.providers.custom.api_base = "https://tenant.test/v1"
    config.providers.custom.api_key = "fixture"
    config.providers.anthropic.api_key = "fixture"
    config.providers.openai.api_key = "fixture"
    preset = config.model_presets["messages"].model_copy(update={"provider": provider_name})
    if provider_name == "openai":
        with pytest.raises(ValueError, match="does not support anthropic_messages"):
            make_provider(config, preset=preset)
    else:
        provider = make_provider(config, preset=preset)
        assert isinstance(provider, AnthropicProvider)
        await provider._client.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_custom_messages_keeps_connection_options_and_tool_history(bind_transport, stream):
    config = _config()
    connection = config.get_provider(preset=config.model_presets["messages"])
    connection.extra_headers = {"X-Gateway": "fixture"}
    connection.extra_query = {"route": "claude"}
    connection.extra_body = {"metadata": {"user_id": "fixture"}}
    requests = []

    def handler(request):
        requests.append(request)
        return _answer(request)

    provider = bind_transport(make_provider(config, preset_name="messages"), handler)
    invoke = provider.chat_stream if stream else provider.chat
    result = await invoke([
        {"role": "system", "content": "Use the lookup result."},
        {"role": "user", "content": "lookup"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "toolu_fixture", "type": "function",
            "function": {"name": "lookup", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "toolu_fixture", "content": "found"},
    ])
    assert result.content == "ok"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/messages"
    assert request.url.params["route"] == "claude"
    assert request.headers["X-Gateway"] == "fixture"
    body = json.loads(request.content)
    assert body["metadata"] == {"user_id": "fixture"}
    assert body["model"] == "claude-sonnet-4-6"
    assert body["system"][0]["text"] == "Use the lookup result."
    assert body["messages"][-2]["content"][0]["type"] == "tool_use"
    assert body["messages"][-1]["content"][0]["type"] == "tool_result"
    assert body["messages"][-1]["content"][0]["tool_use_id"] == "toolu_fixture"


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


async def test_custom_messages_uses_its_proxy_and_does_not_inherit_native_credentials(monkeypatch):
    from anthropic import DefaultAsyncHttpxClient

    config = _config()
    connection = config.get_provider(preset=config.model_presets["messages"])
    connection.api_key = None
    connection.proxy = "http://proxy.test:8080"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "native-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "native-token")
    requests = []

    def handler(request):
        requests.append(request)
        return _answer(request)

    def transport(**kwargs):
        assert kwargs.pop("proxy") == connection.proxy
        assert kwargs["trust_env"] is False
        return DefaultAsyncHttpxClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("anthropic.DefaultAsyncHttpxClient", transport)
    provider = make_provider(config, preset_name="messages")
    try:
        response = await provider.chat([{"role": "user", "content": "hello"}])
        assert response.content == "ok"
        assert len(requests) == 1
        assert requests[0].headers["x-api-key"] == "no-key"
        assert "authorization" not in requests[0].headers
    finally:
        await provider.aclose()
    assert provider._client.is_closed()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider_name", ["tenant", "custom"])
@pytest.mark.parametrize("preferred,path", [
    ("chat_completions", "/v1/chat/completions"),
    ("responses", "/v1/responses"),
    ("anthropic_messages", "/v1/messages"),
])
async def test_connection_default_matches_auto_preview_and_wire(bind_transport, stream, provider_name, preferred, path):
    config = Config.model_validate({"providers": {provider_name: {
        "apiBase": "https://tenant.test/v1",
        "api": {
            "supportedApis": [preferred] if provider_name == "custom" else ["chat_completions", "responses", "anthropic_messages"],
            "preferredApi": preferred,
        },
    }}})
    preset = ModelPresetConfig(provider=provider_name, model=f"{provider_name}/served-model")
    assert resolve_automatic_model_api(config, preset=preset) == (provider_name, preferred)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return _answer(request)

    provider = bind_transport(make_provider(config, preset=preset), handler)
    messages = [{"role": "user", "content": "hello"}]
    invoke = provider.chat_stream if stream else provider.chat
    assert (await invoke(messages, model=preset.model)).content == "ok"
    assert paths == [path]


@pytest.mark.parametrize("preferred", ["responses", "anthropic_messages"])
def test_connection_single_api_constrains_presets_and_reload_signature(preferred):
    config = _config()
    before = provider_signature(config, preset_name="chat")
    connection = config.providers.model_extra["tenant"]
    connection.api = ProviderAPIConfig(supported_apis=(preferred,))
    assert provider_signature(config, preset_name="chat") != before
    auto = ModelPresetConfig(provider="tenant", model="served-model")
    assert resolve_automatic_model_api(config, preset=auto) == ("tenant", preferred)
    validate_provider_setup(config, preset=auto)
    with pytest.raises(ValueError, match="does not accept request APIs"):
        validate_provider_setup(config, preset_name="chat")
    matching = "responses" if preferred == "responses" else "messages"
    validate_provider_setup(config, preset_name=matching)


def test_custom_messages_requires_an_explicit_endpoint():
    config = Config()
    preset = ModelPresetConfig(
        provider="custom", model="served-model",
        api=ModelAPIConfig(supported_apis=("anthropic_messages",)),
    )
    with pytest.raises(ValueError, match="requires api_base"):
        validate_provider_setup(config, preset=preset)


@pytest.mark.parametrize("preset_name,path", [
    ("responses", "/v1/responses"), ("chat", "/v1/chat/completions"), ("messages", "/v1/messages"),
])
async def test_explicit_model_api_overrides_connection_default(bind_transport, preset_name, path):
    config = _config()
    config.providers.model_extra["tenant"].api = ProviderAPIConfig(
        supported_apis=("chat_completions", "responses", "anthropic_messages"),
        preferred_api="anthropic_messages",
    )
    preset = config.model_presets[preset_name]
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return _answer(request)

    provider = bind_transport(make_provider(config, preset=preset), handler)
    assert (await provider.chat([{"role": "user", "content": "hello"}], model=preset.model)).content == "ok"
    assert paths == [path]
