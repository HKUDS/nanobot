import json

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.webui.settings_models import model_settings_payload, provider_models_payload


def _config(model: str = "deepseek/deepseek-v4-flash") -> Config:
    return Config.model_validate({
        "providers": {"shengsuanyun": {"apiKey": "test-key"}},
        "agents": {"defaults": {"provider": "shengsuanyun", "model": model}},
    })


def test_catalog_uses_gateway_credentials_and_preserves_model_ids() -> None:
    def get(url: str, **kwargs: object) -> httpx.Response:
        assert url == "https://router.shengsuanyun.com/api/v1/models"
        assert kwargs["headers"] == {
            "Accept": "application/json", "Authorization": "Bearer test-key",
        }
        return httpx.Response(200, json={"data": [{"id": "deepseek/deepseek-v4-flash"}]},
                              request=httpx.Request("GET", url))

    payload = provider_models_payload(_config(), {"provider": ["shengsuanyun"]}, http_get=get)
    assert payload["status"] == "available"
    assert payload["models"][0]["id"] == "deepseek/deepseek-v4-flash"


def test_settings_exposes_gateway_without_exposing_api_key() -> None:
    payload = model_settings_payload(_config(), oauth_status=lambda _: {
        "configured": False, "account": None, "expires_at": None, "login_supported": False,
    })
    row = next(row for row in payload["providers"] if row["name"] == "shengsuanyun")
    assert row["configured"] is True
    assert row["default_api_base"] == "https://router.shengsuanyun.com/api/v1"
    assert "test-key" not in str(payload)


def test_explicit_gateway_prefix_routes_even_with_another_provider_configured() -> None:
    config = Config.model_validate({
        "providers": {
            "shengsuanyun": {"apiKey": "test-key"},
            "deepseek": {"apiKey": "other-key"},
        },
        "agents": {"defaults": {"model": "shengsuanyun/deepseek/deepseek-v4-flash"}},
    })
    assert config.get_provider_name(config.agents.defaults.model) == "shengsuanyun"
    assert config.get_api_key(config.agents.defaults.model) == "test-key"


@pytest.mark.parametrize("model", [
    "deepseek/deepseek-v4-flash", "shengsuanyun/deepseek/deepseek-v4-flash",
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
