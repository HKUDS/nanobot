"""Tsubasa configuration uses the shared chat transport and model picker."""

import pytest

from nanobot.cli.models import get_model_catalog
from nanobot.config.schema import Config
from nanobot.providers.factory import build_provider_snapshot
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


@pytest.mark.parametrize("model", ["tsubasa-fast", "tsubasa-pro", "tsubasa/tsubasa-pro"])
@pytest.mark.parametrize("api_base", [None, "https://gateway.example/v1"])
def test_tsubasa_factory_routes_credentials_model_and_endpoint(model, api_base):
    provider_config = {"apiKey": "tsubasa-test-key"}
    if api_base:
        provider_config["apiBase"] = api_base
    config = Config.model_validate({
        "providers": {
            "tsubasa": provider_config,
            "openai": {"apiKey": "unrelated-test-key"},
        },
        "modelPresets": {"primary": {
            "provider": "tsubasa", "model": model,
            "contextWindowTokens": 32768, "maxTokens": 4096,
        }},
        "agents": {"defaults": {"modelPreset": "primary"}},
    })

    snapshot = build_provider_snapshot(config)
    provider = snapshot.provider
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.api_key == "tsubasa-test-key"
    assert provider.api_base == (api_base or "https://api.tsubasa.sh/v1")
    assert snapshot.context_window_tokens == 32768
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "Hello"}], tools=None, model=model,
        max_tokens=4096, temperature=0.1, reasoning_effort=None, tool_choice=None,
    )
    assert kwargs["model"] == model.removeprefix("tsubasa/")
    assert kwargs["max_tokens"] == 4096
    assert not {"max_completion_tokens", "tools", "reasoning_effort", "response_format"} & kwargs.keys()


def test_tsubasa_model_picker_uses_static_context_metadata(monkeypatch):
    def unexpected_http(*args, **kwargs):
        pytest.fail("The built-in catalog should not make a network request")

    monkeypatch.setattr("nanobot.cli.models.httpx.get", unexpected_http)
    models = get_model_catalog(Config(), "tsubasa")
    assert [(model.id, model.context_window) for model in models] == [
        ("tsubasa-fast", 32768), ("tsubasa-pro", 32768),
    ]
