"""Factory coverage for automatic Responses state retention and compaction."""

from __future__ import annotations

import json
from unittest.mock import patch

from nanobot.config.loader import save_config
from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.factory import make_provider, provider_signature

_REMOVED_FIELD_NAMES = {
    "responses_state_enabled",
    "responses_compaction_enabled",
    "responses_compact_threshold",
}
_REMOVED_FIELD_ALIASES = {
    "responsesStateEnabled",
    "responsesCompactionEnabled",
    "responsesCompactThreshold",
}


def test_responses_settings_are_not_part_of_provider_config() -> None:
    assert _REMOVED_FIELD_NAMES.isdisjoint(ProviderConfig.model_fields)
    schema_properties = ProviderConfig.model_json_schema(by_alias=True)["properties"]
    assert _REMOVED_FIELD_ALIASES.isdisjoint(schema_properties)

    attempted_override = ProviderConfig.model_validate({
        "responsesStateEnabled": False,
        "responsesCompactionEnabled": False,
        "responsesCompactThreshold": 70_000,
    })
    dumped = attempted_override.model_dump(mode="json", by_alias=True)
    assert _REMOVED_FIELD_ALIASES.isdisjoint(dumped)


def test_save_config_drops_removed_responses_settings(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "providers": {
            "openai": {
                "apiKey": "sk-test",
                "responsesStateEnabled": False,
                "responsesCompactionEnabled": False,
                "responsesCompactThreshold": 70_000,
            },
            "openaiCodex": {
                "apiKey": "codex-secret",
                "proxy": "http://127.0.0.1:23458",
                "extraBody": {"service_tier": "priority"},
                "responsesStateEnabled": False,
                "responsesCompactionEnabled": False,
                "responsesCompactThreshold": 80_000,
            },
            "githubCopilot": {
                "apiKey": "copilot-secret",
                "responsesCompactionEnabled": False,
            },
        },
    })

    save_config(config, config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert _REMOVED_FIELD_ALIASES.isdisjoint(saved["providers"]["openai"])
    assert saved["providers"]["openaiCodex"] == {
        "extraBody": {"service_tier": "priority"},
        "proxy": "http://127.0.0.1:23458",
    }
    assert "githubCopilot" not in saved["providers"]
    assert "codex-secret" not in config_path.read_text(encoding="utf-8")
    assert "copilot-secret" not in config_path.read_text(encoding="utf-8")


def test_factory_enables_responses_features_without_user_settings() -> None:
    base = {
        "agents": {
            "defaults": {
                "model": "gpt-5.6",
                "provider": "openai",
            },
        },
        "providers": {
            "openai": {
                "apiKey": "sk-test",
            },
        },
    }
    config = Config.model_validate(base)

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert provider._responses_state_enabled is True
    assert provider._responses_compaction_enabled is True
    assert provider._responses_compact_threshold is None


def test_removed_responses_settings_do_not_change_provider_behavior() -> None:
    base = {
        "agents": {
            "defaults": {
                "model": "gpt-5.6",
                "provider": "openai",
            },
        },
        "providers": {
            "openai": {
                "apiKey": "sk-test",
            },
        },
    }
    attempted_override = Config.model_validate({
        **base,
        "providers": {
            "openai": {
                **base["providers"]["openai"],
                "responsesStateEnabled": False,
                "responsesCompactionEnabled": False,
                "responsesCompactThreshold": 70_000,
            },
        },
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(attempted_override)

    assert provider._responses_state_enabled is True
    assert provider._responses_compaction_enabled is True
    assert provider._responses_compact_threshold is None
    assert provider_signature(Config.model_validate(base)) == provider_signature(
        attempted_override
    )
