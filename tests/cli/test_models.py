"""CLI model discovery exercises the same provider boundary as WebUI."""

from types import SimpleNamespace

import httpx
import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from nanobot.cli import models, onboard
from nanobot.config.schema import Config, ModelPresetConfig


@pytest.fixture
def catalog_http(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
            {"id": "alpha", "context_length": 123456},
            {"id": "beta"},
        ]})

    monkeypatch.setattr(models.httpx, "get", get)
    return calls


def configured():
    config = Config()
    config.providers.custom.api_base = "https://catalog.example/v1"
    config.providers.custom.api_key = "draft-key"
    return config


def test_catalog_uses_unsaved_endpoint_and_credentials(catalog_http):
    config = configured()
    before = config.model_dump()
    assert models.get_model_context_limit("alpha", "custom", config=config) == 123456
    assert models.get_model_context_limit("beta", "custom", config=config) is None
    assert catalog_http[0][0] == "https://catalog.example/v1/models"
    assert catalog_http[0][1]["headers"]["Authorization"] == "Bearer draft-key"
    assert config.model_dump() == before


def test_auto_provider_uses_edited_model_not_active_preset(catalog_http):
    config = configured()
    config.model_presets["active"] = ModelPresetConfig(model="unrelated", provider="anthropic")
    config.agents.defaults.model_preset = "active"
    assert models.get_model_context_limit("custom/alpha", "auto", config=config) == 123456


def test_autocomplete_fetches_once_and_allows_manual_model(catalog_http, monkeypatch):
    def autocomplete(*args, **kwargs):
        completer = kwargs["completer"]
        event = CompleteEvent()
        assert [c.text for c in completer.get_completions(Document("AL"), event)] == ["alpha"]
        assert [c.text for c in completer.get_completions(Document("be"), event)] == ["beta"]
        return SimpleNamespace(ask=lambda: "not-in-catalog")

    monkeypatch.setattr(onboard, "questionary", SimpleNamespace(autocomplete=autocomplete))
    assert onboard._input_model_with_autocomplete(
        "Model", "", "custom", config=configured(),
    ) == "not-in-catalog"
    assert len(catalog_http) == 1


def test_discovery_failure_keeps_manual_input(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(models.httpx, "get", unavailable)
    assert models.get_model_catalog(configured(), "custom") == []
    assert models.get_model_context_limit("alpha", "custom", config=configured()) is None


def test_unconfigured_provider_does_not_fetch(catalog_http):
    assert models.get_model_catalog(Config(), "openai") == []
    assert catalog_http == []


def test_quick_start_discovery_uses_draft_without_committing_on_back(monkeypatch):
    config = Config()
    before = config.model_dump()
    choices = iter(["OpenRouter", onboard._BACK_PRESSED])
    monkeypatch.setattr(onboard, "_select_with_back", lambda *a, **kw: next(choices))
    monkeypatch.setattr(onboard, "_show_quick_start_progress", lambda *a: None)
    monkeypatch.setattr(onboard, "_input_text", lambda *a: "new-key")

    def model_input(*args, config):
        assert config.providers.openrouter.api_key == "new-key"
        return onboard._BACK_PRESSED

    monkeypatch.setattr(onboard, "_input_model_with_autocomplete", model_input)
    assert onboard._configure_quick_start_provider(config) is onboard._BACK_PRESSED
    assert config.model_dump() == before

