import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.routing import resolve_provider_route
from nanobot.webui.settings_models import (
    create_model_configuration,
    model_settings_payload,
    provider_models_payload,
    update_provider_settings,
)


def _config(model: str = "deepseek/deepseek-v4-flash") -> Config:
    return Config.model_validate({
        "providers": {"shengsuanyunRouter": {"apiKey": "test-key"}},
        "agents": {"defaults": {"provider": "shengsuanyun_router", "model": model}},
    })


def test_catalog_uses_gateway_credentials_and_preserves_model_ids() -> None:
    def get(url: str, **kwargs: object) -> httpx.Response:
        assert url == "https://router.shengsuanyun.com/api/v1/models"
        assert kwargs["headers"] == {
            "Accept": "application/json", "Authorization": "Bearer test-key",
        }
        return httpx.Response(200, json={"data": [{"id": "deepseek/deepseek-v4-flash"}]},
                              request=httpx.Request("GET", url))

    payload = provider_models_payload(_config(), {"provider": ["shengsuanyun_router"]}, http_get=get)
    assert payload["status"] == "available"
    assert payload["models"][0]["id"] == "deepseek/deepseek-v4-flash"


def test_settings_exposes_gateway_without_exposing_api_key() -> None:
    payload = model_settings_payload(_config(), oauth_status=_not_signed_in)
    row = next(row for row in payload["providers"] if row["name"] == "shengsuanyun_router")
    assert row["configured"] is True
    assert row["default_api_base"] == "https://router.shengsuanyun.com/api/v1"
    assert "test-key" not in str(payload)


def _not_signed_in(_: object) -> dict[str, object]:
    return {"configured": False, "account": None, "expires_at": None, "login_supported": False}


def test_existing_custom_shengsuanyun_connection_keeps_anthropic_route(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "providers": {"shengsuanyun": {
            "apiKey": "old-key",
            "apiBase": "https://router.shengsuanyun.com/api",
            "api": {"supportedApis": ["anthropic_messages"], "preferredApi": "anthropic_messages"},
        }},
        "agents": {"defaults": {"provider": "shengsuanyun", "model": "anthropic/claude-sonnet-4-6"}},
    }), encoding="utf-8")

    config = load_config(path)
    route = resolve_provider_route(config, preset=config.resolve_preset())
    assert route.backend == "anthropic"
    assert config.get_api_base() == "https://router.shengsuanyun.com/api"
    row = next(item for item in model_settings_payload(
        config, oauth_status=_not_signed_in,
    )["providers"] if item["name"] == "shengsuanyun")
    assert row["is_custom"] and row["provider_api_configurable"]

    assert update_provider_settings(config, {
        "provider": ["shengsuanyun"], "api_key": ["rotated-key"], "display_name": [row["label"]],
    })[0]
    save_config(config, path)
    reloaded = load_config(path)
    assert reloaded.get_api_key() == "rotated-key"
    assert resolve_provider_route(reloaded, preset=reloaded.resolve_preset()).backend == "anthropic"


def test_explicit_gateway_prefix_routes_even_with_another_provider_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "shengsuanyunRouter": {"apiKey": "test-key"},
            "deepseek": {"apiKey": "other-key"},
        },
        "agents": {"defaults": {"model": "shengsuanyun_router/deepseek/deepseek-v4-flash"}},
    })
    assert config.get_provider_name(config.agents.defaults.model) == "shengsuanyun_router"
    assert config.get_api_key(config.agents.defaults.model) == "test-key"


@pytest.mark.parametrize("model", [
    "deepseek/deepseek-v4-flash", "shengsuanyun_router/deepseek/deepseek-v4-flash",
])
async def test_chat_and_stream_route_model_and_tools(model: str) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert str(request.url) == "https://router.shengsuanyun.com/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert requests[-1]["model"] == "deepseek/deepseek-v4-flash"
        assert requests[-1]["tools"][0]["function"]["name"] == "weather"
        if requests[-1].get("stream"):
            events = [
                {"id": "1", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0, "delta": {"content": "Hello"},
                                               "finish_reason": None}]},
                {"id": "1", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            content = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
            return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            "id": "1", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "weather", "arguments": '{"city":"Shanghai"}'},
                }],
            }}],
        })

    provider = make_provider(_config(model))
    assert isinstance(provider, OpenAICompatProvider)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider._client = AsyncOpenAI(api_key="test-key", base_url=provider._effective_base,
                                      http_client=http, max_retries=0)
        tools = [{"type": "function", "function": {"name": "weather", "parameters": {"type": "object"}}}]
        result = await provider.chat([{"role": "user", "content": "Weather?"}], tools=tools)
        assert result.tool_calls[0].name == "weather"
        assert result.tool_calls[0].arguments == {"city": "Shanghai"}
        deltas = []

        async def on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream([{"role": "user", "content": "Hi"}], tools=tools,
                                            on_content_delta=on_delta)
        assert result.content == "Hello"
        assert deltas == ["Hello"]
    assert len(requests) == 2


async def test_saved_responses_preset_uses_router_with_full_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config.model_validate({"providers": {"openai": {"apiKey": "other-key"}}})
    assert update_provider_settings(config, {
        "provider": ["shengsuanyun_router"], "api_key": ["test-key"],
    })[0]
    name = create_model_configuration(config, {
        "name": ["Router GPT"],
        "provider": ["shengsuanyun_router"],
        "model": ["openai/gpt-5.4"],
        "api": ['{"supportedApis":["responses"],"preferredApi":"responses"}'],
    }, oauth_status=_not_signed_in)
    path = tmp_path / "config.json"
    save_config(config, path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://router.shengsuanyun.com/api/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-5.4"
        assert body["input"][0]["content"][0]["text"] == "Hi"
        return httpx.Response(200, json={
            "id": "resp_1", "object": "response", "status": "completed",
            "output": [{
                "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "Hello", "annotations": []}],
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        def create_client(**kwargs):
            return AsyncOpenAI(**(kwargs | {"http_client": http}))

        monkeypatch.setattr("nanobot.providers.openai_compat_provider.AsyncOpenAI", create_client)
        provider = make_provider(load_config(path), preset_name=name)
        try:
            response = await provider.chat([{"role": "user", "content": "Hi"}])
            assert response.content == "Hello"
        finally:
            await provider.aclose()
