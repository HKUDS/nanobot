"""Configuration coverage for Responses state retention and compaction."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.factory import make_provider, provider_signature


def test_responses_settings_accept_camel_case_and_omit_defaults() -> None:
    defaults = ProviderConfig().model_dump(mode="json", by_alias=True)
    assert "responsesStateEnabled" not in defaults
    assert "responsesCompactionEnabled" not in defaults
    assert "responsesCompactThreshold" not in defaults

    provider = ProviderConfig.model_validate({
        "responsesStateEnabled": False,
        "responsesCompactionEnabled": False,
        "responsesCompactThreshold": 75_000,
    })

    assert provider.responses_state_enabled is False
    assert provider.responses_compaction_enabled is False
    assert provider.responses_compact_threshold == 75_000
    assert provider.model_dump(
        mode="json",
        by_alias=True,
        exclude_defaults=True,
        exclude_none=True,
    ) == {
        "responsesStateEnabled": False,
        "responsesCompactionEnabled": False,
        "responsesCompactThreshold": 75_000,
    }


def test_responses_compact_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate({"responsesCompactThreshold": 0})


def test_oauth_responses_settings_round_trip_without_credentials(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "providers": {
            "openaiCodex": {
                "apiKey": "codex-secret",
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

    raw = config_path.read_text(encoding="utf-8")
    saved = json.loads(raw)
    assert saved["providers"]["openaiCodex"] == {
        "responsesStateEnabled": False,
        "responsesCompactionEnabled": False,
        "responsesCompactThreshold": 80_000,
    }
    assert saved["providers"]["githubCopilot"] == {
        "responsesCompactionEnabled": False,
    }
    assert "codex-secret" not in raw
    assert "copilot-secret" not in raw

    reloaded = load_config(config_path)
    assert reloaded.providers.openai_codex.responses_state_enabled is False
    assert reloaded.providers.openai_codex.responses_compact_threshold == 80_000
    assert reloaded.providers.github_copilot.responses_compaction_enabled is False


def test_factory_applies_responses_settings_and_tracks_them_in_signature() -> None:
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
                "responsesStateEnabled": False,
                "responsesCompactionEnabled": False,
                "responsesCompactThreshold": 70_000,
            },
        },
    }
    config = Config.model_validate(base)

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert provider._responses_state_enabled is False
    assert provider._responses_compaction_enabled is False
    assert provider._responses_compact_threshold == 70_000

    changed = Config.model_validate({
        **base,
        "providers": {
            "openai": {
                **base["providers"]["openai"],
                "responsesStateEnabled": True,
            },
        },
    })
    assert provider_signature(config) != provider_signature(changed)
