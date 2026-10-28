"""Catalog boundary contracts shared by the CLI and WebUI."""

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.webui.settings_models import provider_models_payload


@pytest.mark.parametrize("api_base", [None, "https://api.aimlapi.com/v1/"])
def test_official_aimlapi_catalog_only_exposes_chat_models(api_base):
    provider_name = "aiml_api"
    connection = {"apiKey": "test-key"}
    if api_base:
        connection["apiBase"] = api_base
    config = Config.model_validate({"providers": {provider_name: connection}})

    def get(url, **kwargs):
        assert url == "https://api.aimlapi.com/v1/models"
        assert kwargs["follow_redirects"] is False
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
            {"id": "openai/gpt-4o", "type": "openai/chat-completions", "info": {
                "name": "GPT-4o", "developer": "OpenAI", "contextLength": 128000,
                "description": "Chat model",
            }},
            {"id": "openai/gpt-4o", "type": "openai/chat-completions"},
            {"id": "image", "type": "openai/image-generations"},
            {"id": "video", "type": "internal/video-generations/submit"},
            {"id": "embedding", "type": "openai/embeddings"},
            {"id": "responses", "type": "openai/responses/submit"},
            {"id": "messages", "type": "anthropic/messages"},
            {"id": "unknown"},
            {"id": "retired", "type": "openai/chat-completions", "shutdown_date": "2020-01-01"},
        ]})

    payload = provider_models_payload(config, {"provider": [provider_name]}, http_get=get)
    assert payload["status"] == "available"
    assert payload["model_count"] == 1
    assert payload["models"] == [{
        "id": "openai/gpt-4o", "label": "GPT-4o", "owned_by": "OpenAI",
        "context_window": 128000, "description": "Chat model",
    }]


@pytest.mark.parametrize("provider_name", ["aimlapi", "aiml_api"])
def test_custom_endpoint_keeps_standard_openai_catalog(provider_name):
    config = Config.model_validate({"providers": {provider_name: {
        "apiBase": "https://proxy.example.test/v1", "apiKey": "test-key",
    }}})

    def get(url, **kwargs):
        assert url == "https://proxy.example.test/v1/models"
        return httpx.Response(200, request=httpx.Request("GET", url), json={
            "data": [{"id": "local-model", "owned_by": "research"}],
        })

    payload = provider_models_payload(config, {"provider": [provider_name]}, http_get=get)
    assert payload["status"] == "available"
    assert payload["models"][0]["id"] == "local-model"


def test_legacy_custom_connection_keeps_other_request_api_models():
    config = Config.model_validate({"providers": {"aimlapi": {
        "apiBase": "https://api.aimlapi.com/v1",
        "api": {"supportedApis": ["responses"]},
    }}})

    def get(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
            {"id": "openai/model", "type": "openai/responses/submit"},
        ]})

    payload = provider_models_payload(config, {"provider": ["aimlapi"]}, http_get=get)
    assert payload["models"][0]["id"] == "openai/model"
