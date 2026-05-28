from __future__ import annotations

import json

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.webui.settings_api import (
    WebUISettingsError,
    _oauth_provider_status,
    create_model_configuration,
    settings_payload,
    update_model_configuration,
    update_network_safety_settings,
)
from nanobot.providers.registry import find_by_name


def test_create_model_configuration_writes_label_and_selects(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.model = "openai/gpt-4o"
    config.agents.defaults.provider = "openai"
    config.providers.openai.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = create_model_configuration(
        {
            "label": ["Fast writing"],
            "provider": ["openai"],
            "model": ["openai/gpt-4.1-mini"],
        }
    )

    assert payload["agent"]["model_preset"] == "fast-writing"
    assert payload["agent"]["model"] == "openai/gpt-4.1-mini"
    rows = {row["name"]: row for row in payload["model_presets"]}
    assert rows["fast-writing"]["label"] == "Fast writing"

    saved = load_config(config_path)
    assert saved.agents.defaults.model_preset == "fast-writing"
    assert saved.model_presets["fast-writing"].label == "Fast writing"
    assert saved.model_presets["fast-writing"].model == "openai/gpt-4.1-mini"
    assert saved.model_presets["fast-writing"].provider == "openai"

    with pytest.raises(WebUISettingsError) as duplicate:
        create_model_configuration(
            {
                "label": ["Fast writing"],
                "provider": ["openai"],
                "model": ["openai/gpt-4.1-mini"],
            }
        )
    assert duplicate.value.status == 409


def test_create_model_configuration_rejects_unconfigured_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="provider is not configured"):
        create_model_configuration(
            {
                "label": ["Deep"],
                "provider": ["openai"],
                "model": ["openai/gpt-4.1"],
            }
        )


def test_update_model_configuration_edits_named_preset_and_selects(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_key = "sk-test"
    config.model_presets["codex"] = ModelPresetConfig(
        label="Old Codex",
        provider="openai",
        model="openai/gpt-4.1",
    )
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "nanobot.webui.settings_api._oauth_provider_status",
        lambda spec: {
            "configured": spec.name == "openai_codex",
            "account": "acct-test",
            "expires_at": 123,
            "login_supported": True,
        },
    )

    payload = update_model_configuration(
        {
            "name": ["codex"],
            "label": ["Codex"],
            "provider": ["openai_codex"],
            "model": ["openai-codex/gpt-5.5"],
        }
    )

    assert payload["agent"]["model_preset"] == "codex"
    assert payload["agent"]["model"] == "openai-codex/gpt-5.5"
    saved = load_config(config_path)
    assert saved.agents.defaults.model_preset == "codex"
    assert saved.model_presets["codex"].label == "Codex"
    assert saved.model_presets["codex"].provider == "openai_codex"
    assert saved.model_presets["codex"].model == "openai-codex/gpt-5.5"


def test_update_model_configuration_rejects_default_preset(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="model configuration is required"):
        update_model_configuration({"name": ["default"], "model": ["openai/gpt-4.1"]})


def test_settings_payload_includes_oauth_provider_status(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def fake_oauth_status(spec):
        if spec.name == "openai_codex":
            return {
                "configured": True,
                "account": "acct-test",
                "expires_at": 123,
                "login_supported": True,
            }
        return {
            "configured": False,
            "account": None,
            "expires_at": None,
            "login_supported": True,
        }

    monkeypatch.setattr("nanobot.webui.settings_api._oauth_provider_status", fake_oauth_status)

    payload = settings_payload()
    providers = {row["name"]: row for row in payload["providers"]}

    assert providers["openai_codex"]["auth_type"] == "oauth"
    assert providers["openai_codex"]["configured"] is True
    assert providers["openai_codex"]["oauth_account"] == "acct-test"


def test_settings_payload_includes_network_safety_fields(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.tools.webui_allow_local_service_access = False
    config.tools.ssrf_whitelist = ["100.64.0.0/10"]
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = settings_payload()

    assert payload["advanced"]["webui_allow_local_service_access"] is False
    assert payload["advanced"]["allow_local_preview_access"] is False
    assert payload["advanced"]["webui_default_access_mode"] == "default"
    assert payload["advanced"]["private_service_protection_enabled"] is True
    assert payload["advanced"]["ssrf_whitelist_count"] == 1


def test_update_network_safety_settings_writes_local_service_flag(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = update_network_safety_settings(
        {
            "webui_allow_local_service_access": ["false"],
            "webui_default_access_mode": ["full"],
        }
    )

    saved = load_config(config_path)
    saved_raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved.tools.webui_allow_local_service_access is False
    assert saved_raw["tools"]["webuiAllowLocalServiceAccess"] is False
    assert "allowLocalPreviewAccess" not in saved_raw["tools"]
    assert payload["advanced"]["webui_allow_local_service_access"] is False
    assert payload["advanced"]["webui_default_access_mode"] == "full"
    assert payload["requires_restart"] is True


def test_update_network_safety_settings_accepts_legacy_restricted_default_access(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = update_network_safety_settings({"webui_default_access_mode": ["restricted"]})

    assert payload["advanced"]["webui_default_access_mode"] == "default"


def test_update_network_safety_settings_default_access_is_webui_only(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    before = config_path.read_text(encoding="utf-8")
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = update_network_safety_settings({"webui_default_access_mode": ["full"]})

    saved = load_config(config_path)
    assert config_path.read_text(encoding="utf-8") == before
    assert saved.tools.restrict_to_workspace is False
    assert payload["advanced"]["webui_default_access_mode"] == "full"
    assert payload["requires_restart"] is False


def test_openai_codex_oauth_status_uses_available_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_token():
        return type(
            "Token",
            (),
            {
                "access": "access-token",
                "refresh": "refresh-token",
                "expires": 2_000_000_000_000,
                "account_id": "acct-codex",
            },
        )()

    monkeypatch.setattr("oauth_cli_kit.get_token", fake_get_token)

    status = _oauth_provider_status(find_by_name("openai_codex"))

    assert status["configured"] is True
    assert status["account"] == "acct-codex"


def test_openai_codex_oauth_status_rejects_unavailable_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_token():
        raise RuntimeError("refresh failed")

    monkeypatch.setattr("oauth_cli_kit.get_token", fake_get_token)

    status = _oauth_provider_status(find_by_name("openai_codex"))

    assert status["configured"] is False
    assert status["account"] is None


def test_create_model_configuration_accepts_configured_oauth_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "nanobot.webui.settings_api._oauth_provider_status",
        lambda spec: {
            "configured": spec.name == "openai_codex",
            "account": "acct-test",
            "expires_at": 123,
            "login_supported": True,
        },
    )

    payload = create_model_configuration(
        {
            "label": ["Codex"],
            "provider": ["openai_codex"],
            "model": ["openai-codex/gpt-5.1-codex"],
        }
    )

    assert payload["agent"]["model_preset"] == "codex"
    saved = load_config(config_path)
    assert saved.model_presets["codex"].provider == "openai_codex"
