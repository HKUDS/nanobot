"""A new built-in must not take over existing custom AIMLAPI connections."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.routing import resolve_provider_route


@pytest.mark.parametrize("forced", ["auto", "aimlapi"])
@pytest.mark.parametrize("api_key", [None, "test-key"])
@pytest.mark.parametrize("api_base", ["https://proxy.example.test/v1", "https://api.aimlapi.com/v1"])
def test_legacy_connection_survives_config_roundtrip(tmp_path, forced, api_key, api_base):
    config = Config.model_validate({
        "providers": {
            "aimlapi": {
                "apiBase": api_base,
                "apiKey": api_key,
                "displayName": "Research proxy",
                "api": {"supportedApis": ["chat_completions", "responses"]},
                "extraHeaders": {"X-Research": "nanobot"},
            },
            "openrouter": {"apiKey": "other-key"},
        },
        "agents": {"defaults": {"provider": forced, "model": "aimlapi/openai/gpt-4o"}},
    })
    path = tmp_path / "config.json"
    save_config(config, path)
    restored = load_config(path)
    for candidate in (config, restored):
        route = resolve_provider_route(candidate, preset=candidate.resolve_preset())
        assert route.provider_name == "aimlapi"
        assert candidate.get_api_base() == api_base
        assert route.spec.is_direct
        assert route.spec.label == "Research proxy"
        assert route.spec.request_model_name(route.model) == "openai/gpt-4o"
        assert route.model_api.supported_apis == ("chat_completions", "responses")
        assert route.provider_config.extra_headers == {"X-Research": "nanobot"}


@pytest.mark.parametrize("custom_order", [("aimlapi", "second"), ("second", "aimlapi")])
@pytest.mark.parametrize("with_gateway", [False, True])
def test_legacy_automatic_fallback_order_survives_save(tmp_path, custom_order, with_gateway):
    providers = {
        name: {"apiBase": f"https://{name}.example.test/v1", "apiKey": "test-key"}
        for name in custom_order
    }
    if with_gateway:
        providers["edenai"] = {"apiKey": "other-key"}
    config = Config.model_validate({
        "providers": providers,
        "agents": {"defaults": {"model": "unqualified-model", "provider": "auto"}},
    })
    expected = "edenai" if with_gateway else custom_order[0]
    path = tmp_path / "config.json"
    save_config(config, path)
    assert config.get_provider_name() == expected
    assert load_config(path).get_provider_name() == expected


@pytest.mark.parametrize("api", ["responses", "anthropic_messages"])
def test_legacy_connection_keeps_declared_adapter(api):
    config = Config.model_validate({
        "providers": {"aimlapi": {
            "apiBase": "https://proxy.example.test/v1",
            "api": {"supportedApis": [api]},
        }},
        "agents": {"defaults": {"model": "aimlapi/vendor/model", "provider": "aimlapi"}},
    })
    route = resolve_provider_route(config, preset=config.resolve_preset())
    assert route.model_api.preferred_api == api
    assert route.backend == ("anthropic" if api == "anthropic_messages" else "openai_compat")


@pytest.mark.parametrize("provider_name", ["aimlapi", "aiml_api"])
@pytest.mark.parametrize("user_attribution", [{}, {
    "X-AIMLAPI-Source": "user-opt-in", "X-Title": "Research", "X-AIMLAPI-Partner-ID": "part_UserChoice",
}])
async def test_real_sdk_request_preserves_payload_and_only_user_attribution(monkeypatch, provider_name, user_attribution):
    """Capture the SDK HTTP boundary; no credentials or paid API calls are used."""
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": "openai/gpt-4o",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "ok",
            }}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        def client_factory(**kwargs):
            kwargs["http_client"] = http_client
            return AsyncOpenAI(**kwargs)

        monkeypatch.setattr("nanobot.providers.openai_compat_provider.AsyncOpenAI", client_factory)
        connection = {"apiKey": "test-key", "extraHeaders": {"X-Research": "nanobot", **user_attribution}}
        if provider_name == "aimlapi":
            connection["apiBase"] = "https://proxy.example.test/v1"
        config = Config.model_validate({
            "providers": {provider_name: connection},
            "agents": {"defaults": {
                "model": f"{provider_name}/openai/gpt-4o", "provider": provider_name,
            }},
        })
        provider = make_provider(config)
        messages = [{"role": "system", "content": "Stable prefix"}, {"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {
            "name": "lookup", "description": "Look up a value", "parameters": {"type": "object"},
        }}]
        result = await provider.chat(messages=messages, tools=tools, reasoning_effort="medium")
        assert result.content == "ok"
    assert len(requests) == 1
    request = requests[0]
    expected_base = connection.get("apiBase", "https://api.aimlapi.com/v1")
    assert str(request.url) == expected_base + "/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-4o"
    assert body["messages"] == messages
    assert body["tools"] == tools
    assert body["reasoning_effort"] == "medium"
    assert request.headers["x-research"] == "nanobot"
    attribution = {
        key: value for key, value in request.headers.items()
        if key.startswith("x-aimlapi-") or key in {"http-referer", "x-title"}
    }
    assert attribution == {key.lower(): value for key, value in user_attribution.items()}
