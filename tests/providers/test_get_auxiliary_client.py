"""Tests for get_auxiliary_client factory (M1 Task D4)."""

from __future__ import annotations

from unittest.mock import patch

from nanobot.config.schema import Config
from nanobot.providers.factory import get_auxiliary_client


def _config_with(aux_preset: str | None) -> Config:
    """Build a minimal Config with main + optional auxiliary preset."""
    payload: dict = {
        "modelPresets": {
            "main": {"model": "gpt-4o-mini", "provider": "openai"},
            "aux-real": {"model": "gpt-4o-mini", "provider": "openai"},
        },
        "providers": {
            "openai": {"apiKey": "sk-test"},
        },
        "agents": {"defaults": {"modelPreset": "main"}},
    }
    if aux_preset is not None:
        payload["agents"]["defaults"]["auxiliary"] = {"modelPreset": aux_preset}
    return Config.model_validate(payload)


def test_get_auxiliary_client_uses_named_preset_when_set():
    cfg = _config_with("aux-real")
    captured: dict[str, object] = {}

    def _fake_make_provider(config, *, preset=None, preset_name=None, model=None):
        captured["preset"] = preset
        captured["preset_name"] = preset_name
        return object()  # sentinel provider

    with patch("nanobot.providers.factory.make_provider", side_effect=_fake_make_provider):
        client = get_auxiliary_client(cfg)
    assert client is not None
    assert captured["preset"] is not None
    assert captured["preset"].model == cfg.model_presets["aux-real"].model


def test_get_auxiliary_client_falls_back_to_main_when_unset():
    cfg = _config_with(None)
    captured: dict[str, object] = {}

    def _fake_make_provider(config, *, preset=None, preset_name=None, model=None):
        captured["preset"] = preset
        return object()

    with patch("nanobot.providers.factory.make_provider", side_effect=_fake_make_provider):
        client = get_auxiliary_client(cfg)
    assert client is not None
    # Fallback uses the main preset (whichever defaults.modelPreset is)
    assert captured["preset"] is not None
    assert captured["preset"].model == cfg.model_presets["main"].model
