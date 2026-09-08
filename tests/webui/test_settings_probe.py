"""Setup checks exercise one selected model without touching chat or saved configuration."""

from unittest.mock import AsyncMock

import pytest

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import LLMResponse
from nanobot.webui.settings_probe import test_provider_connection as probe


async def test_probe_uses_explicit_model_without_tools_or_fallback(monkeypatch):
    config = Config()
    config.model_presets["fallback"] = ModelPresetConfig(provider="openai", model="other")
    config.agents.defaults.fallback_models = ["fallback"]
    original = config.model_dump()
    chat = AsyncMock(return_value=LLMResponse(content="Hello!"))
    presets = []

    def make(_config, *, preset):
        assert _config.agents.defaults.fallback_models == []
        presets.append(preset)
        return type("Provider", (), {"chat": chat})()

    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider", make)
    result = await probe(config, {"provider": "anthropic", "model": "my-model"})
    assert result["status"] == "ok"
    assert result["message"] == "Hello!"
    assert presets[0].provider == "anthropic"
    chat.assert_awaited_once_with(
        [{"role": "user", "content": "Reply with a short hello."}],
        model="my-model", max_tokens=256, temperature=0.1, reasoning_effort=None,
    )
    assert config.model_dump() == original


@pytest.mark.parametrize(("status", "kind", "expected"), [
    (401, None, "Access denied"), (403, None, "Access denied"),
    (404, None, "not found"), (429, None, "limit reached"),
    (None, "timeout", "Could not reach"), (None, "connection", "Could not reach"),
    (500, None, "No model reply"),
])
async def test_probe_errors_are_actionable_and_do_not_echo_secrets(monkeypatch, status, kind, expected):
    chat = AsyncMock(return_value=LLMResponse(content="secret-api-key", finish_reason="error",
                                             error_status_code=status, error_kind=kind))
    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider",
                        lambda *_args, **_kwargs: type("Provider", (), {"chat": chat})())
    result = await probe(Config(), {"provider": "anthropic", "model": "my-model"})
    assert result["status"] == "error"
    assert expected in result["message"]
    assert "secret-api-key" not in str(result)


async def test_probe_timeout_is_recoverable(monkeypatch):
    chat = AsyncMock(side_effect=TimeoutError("secret-upstream-data"))
    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider",
                        lambda *_args, **_kwargs: type("Provider", (), {"chat": chat})())
    result = await probe(Config(), {"provider": "anthropic", "model": "my-model"})
    assert result["status"] == "error"
    assert "Could not reach" in result["message"]
    assert "secret" not in str(result)


@pytest.mark.parametrize("payload", [{}, {"provider": "auto", "model": "test"},
                                     {"provider": "anthropic", "model": 123}])
async def test_invalid_probe_does_not_create_a_provider(monkeypatch, payload):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid input must not reach a provider")
    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider", forbidden)
    assert (await probe(Config(), payload))["status"] == "error"


async def test_probe_uses_saved_preset_generation_settings_without_changing_default(monkeypatch):
    config = Config()
    config.model_presets["Coding"] = ModelPresetConfig(
        provider="anthropic", model="coding-model", max_tokens=128,
        temperature=0.7, reasoning_effort="high",
    )
    original = config.model_dump()
    chat = AsyncMock(return_value=LLMResponse(content="Hello!"))

    def make(probe_config, *, preset):
        assert preset == config.model_presets["Coding"]
        assert probe_config.agents.defaults.fallback_models == []
        return type("Provider", (), {"chat": chat})()

    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider", make)
    result = await probe(config, {"preset_name": "Coding"})
    assert result["status"] == "ok"
    chat.assert_awaited_once_with(
        [{"role": "user", "content": "Reply with a short hello."}],
        model="coding-model", max_tokens=128, temperature=0.7, reasoning_effort="high",
    )
    assert config.model_dump() == original


async def test_probe_rejects_missing_saved_preset(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing preset must not make a model request")

    monkeypatch.setattr("nanobot.webui.settings_probe.make_provider", forbidden)
    assert (await probe(Config(), {"preset_name": "missing"}))["status"] == "error"
