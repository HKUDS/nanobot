from __future__ import annotations

import json

import httpx
import pytest

from blackcat.config.loader import load_config, save_config
from blackcat.config.schema import Config, ModelPresetConfig
from blackcat.providers.registry import find_by_name
from blackcat.webui.settings_api import (
    WebUISettingsError,
    _oauth_provider_status,
    create_model_configuration,
    provider_models_payload,
    settings_payload,
    settings_usage_payload,
    update_agent_settings,
    update_model_configuration,
    update_network_safety_settings,
    update_transcription_settings,
)


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
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

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
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

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
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "blackcat.webui.settings_api._oauth_provider_status",
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


def test_update_agent_settings_accepts_context_window_options(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = update_agent_settings({"context_window_tokens": ["262144"]})

    assert payload["agent"]["context_window_tokens"] == 262144
    saved = load_config(config_path)
    assert saved.agents.defaults.context_window_tokens == 262144


def test_update_model_configuration_accepts_context_window_options(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.model_presets["codex"] = ModelPresetConfig(
        label="Codex",
        provider="openai",
        model="openai/gpt-4.1",
    )
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = update_model_configuration(
        {
            "name": ["codex"],
            "context_window_tokens": ["262144"],
        }
    )

    assert payload["agent"]["context_window_tokens"] == 262144
    saved = load_config(config_path)
    assert saved.model_presets["codex"].context_window_tokens == 262144


def test_update_context_window_rejects_unknown_values(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="context_window_tokens must be 65536 or 262144"):
        update_agent_settings({"context_window_tokens": ["128000"]})


def test_update_model_configuration_rejects_default_preset(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="model configuration is required"):
        update_model_configuration({"name": ["default"], "model": ["openai/gpt-4.1"]})


def test_settings_payload_includes_oauth_provider_status(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

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

    monkeypatch.setattr("blackcat.webui.settings_api._oauth_provider_status", fake_oauth_status)

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
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr("blackcat.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = settings_payload()

    assert payload["advanced"]["webui_allow_local_service_access"] is False
    assert payload["advanced"]["allow_local_preview_access"] is False
    assert payload["advanced"]["webui_default_access_mode"] == "default"
    assert payload["advanced"]["private_service_protection_enabled"] is True
    assert payload["advanced"]["ssrf_whitelist_count"] == 1


def test_settings_payload_includes_exec_path_flags(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.tools.exec.path_prepend = "/venv/bin"
    config.tools.exec.path_append = "/usr/sbin"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = settings_payload()

    assert payload["advanced"]["exec_path_prepend_set"] is True
    assert payload["advanced"]["exec_path_append_set"] is True


def test_settings_payload_includes_effective_transcription_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.channels.transcription_provider = "openai"
    config.channels.transcription_language = "en"
    config.providers.openai.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    assert payload["transcription"]["enabled"] is True
    assert payload["transcription"]["provider"] == "openai"
    assert payload["transcription"]["provider_configured"] is True
    assert payload["transcription"]["model"] == "whisper-1"
    assert payload["transcription"]["language"] == "en"


def test_settings_payload_exposes_openrouter_transcription_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openrouter.api_key = "sk-or-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    providers = {provider["name"]: provider for provider in payload["transcription"]["providers"]}
    assert providers["openrouter"]["label"] == "OpenRouter"
    assert providers["openrouter"]["configured"] is True


def test_settings_payload_exposes_siliconflow_transcription_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.siliconflow.api_key = "sf-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    providers = {provider["name"]: provider for provider in payload["transcription"]["providers"]}
    assert providers["siliconflow"]["label"] == "SiliconFlow"
    assert providers["siliconflow"]["configured"] is True
    assert providers["siliconflow"]["default_api_base"] == "https://api.siliconflow.cn/v1"


def test_settings_payload_exposes_xiaomi_mimo_transcription_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.xiaomi_mimo.api_key = "mimo-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    providers = {provider["name"]: provider for provider in payload["transcription"]["providers"]}
    assert providers["xiaomi_mimo"]["label"] == "Xiaomi MIMO"
    assert providers["xiaomi_mimo"]["configured"] is True


def test_settings_payload_exposes_assemblyai_transcription_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "assemblyai"
    config.providers.assemblyai.api_key = "aai-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = settings_payload()

    assert payload["transcription"]["provider"] == "assemblyai"
    assert payload["transcription"]["provider_configured"] is True
    providers = {provider["name"]: provider for provider in payload["transcription"]["providers"]}
    assert providers["assemblyai"]["label"] == "AssemblyAI"
    assert providers["assemblyai"]["configured"] is True
    assert providers["assemblyai"]["default_api_base"] == "https://api.assemblyai.com/v2"
    provider_rows = {provider["name"]: provider for provider in payload["providers"]}
    assert provider_rows["assemblyai"]["configured"] is True
    assert provider_rows["assemblyai"]["model_selectable"] is False


def test_model_configuration_rejects_transcription_only_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.assemblyai.api_key = "aai-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="does not support chat models"):
        create_model_configuration(
            {
                "label": ["Voice only"],
                "provider": ["assemblyai"],
                "model": ["universal-3-pro"],
            }
        )


def test_update_transcription_settings_writes_top_level_only(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.channels.transcription_provider = "openai"
    config.channels.transcription_language = "en"
    config.providers.groq.api_key = "gsk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = update_transcription_settings(
        {
            "enabled": ["true"],
            "provider": ["groq"],
            "model": ["whisper-large-v3-turbo"],
            "language": ["ko"],
            "maxDurationSec": ["90"],
            "maxUploadMb": ["20"],
        }
    )

    saved = load_config(config_path)
    assert saved.channels.transcription_provider == "openai"
    assert saved.channels.transcription_language == "en"
    assert saved.transcription.enabled is True
    assert saved.transcription.provider == "groq"
    assert saved.transcription.model == "whisper-large-v3-turbo"
    assert saved.transcription.language == "ko"
    assert saved.transcription.max_duration_sec == 90
    assert saved.transcription.max_upload_mb == 20
    assert payload["transcription"]["provider"] == "groq"
    assert payload["transcription"]["provider_configured"] is True


def test_update_transcription_settings_accepts_openrouter(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openrouter.api_key = "sk-or-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = update_transcription_settings(
        {
            "provider": ["openrouter"],
            "model": ["nvidia/parakeet-tdt-0.6b-v3"],
        }
    )

    saved = load_config(config_path)
    assert saved.transcription.provider == "openrouter"
    assert saved.transcription.model == "nvidia/parakeet-tdt-0.6b-v3"
    assert payload["transcription"]["provider"] == "openrouter"
    assert payload["transcription"]["provider_configured"] is True


def test_update_transcription_settings_accepts_xiaomi_mimo(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.xiaomi_mimo.api_key = "mimo-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = update_transcription_settings(
        {
            "provider": ["xiaomi_mimo"],
            "model": ["mimo-v2.5-asr"],
            "language": ["zh"],
        }
    )

    saved = load_config(config_path)
    assert saved.transcription.provider == "xiaomi_mimo"
    assert saved.transcription.model == "mimo-v2.5-asr"
    assert saved.transcription.language == "zh"
    assert payload["transcription"]["provider"] == "xiaomi_mimo"
    assert payload["transcription"]["provider_configured"] is True


def test_update_transcription_settings_accepts_assemblyai(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.assemblyai.api_key = "aai-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = update_transcription_settings(
        {
            "provider": ["assemblyai"],
            "model": ["universal-3-pro"],
        }
    )

    saved = load_config(config_path)
    assert saved.transcription.provider == "assemblyai"
    assert saved.transcription.model == "universal-3-pro"
    assert payload["transcription"]["provider"] == "assemblyai"
    assert payload["transcription"]["provider_configured"] is True


def test_update_transcription_settings_validates_language(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="transcription language"):
        update_transcription_settings({"language": ["en-US"]})


def test_settings_payload_includes_token_usage_summary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    from nanobot.webui.token_usage import record_token_usage

    record_token_usage({"prompt_tokens": 10, "completion_tokens": 5})

    payload = settings_payload()

    assert payload["usage"]["total_tokens_30d"] == 15
    assert payload["usage"]["total_tokens"] == 15
    assert payload["usage"]["peak_day_tokens"] == 15
    assert payload["usage"]["current_streak_days"] == 1
    assert payload["usage"]["longest_streak_days"] == 1
    assert payload["usage"]["active_days_30d"] == 1
    assert payload["usage"]["requests_30d"] == 1


def test_settings_usage_payload_returns_lightweight_token_usage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    from nanobot.webui.token_usage import record_token_usage

    record_token_usage({"prompt_tokens": 20, "completion_tokens": 2})

    payload = settings_usage_payload()

    assert payload["total_tokens"] == 22
    assert payload["requests_30d"] == 1
    assert "agent" not in payload


def test_update_network_safety_settings_writes_local_service_flag(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr("blackcat.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

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
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr("blackcat.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    payload = update_network_safety_settings({"webui_default_access_mode": ["restricted"]})

    assert payload["advanced"]["webui_default_access_mode"] == "default"


def test_update_network_safety_settings_default_access_is_webui_only(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    before = config_path.read_text(encoding="utf-8")
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr("blackcat.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

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


def test_provider_models_payload_fetches_openai_compatible_models(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.deepseek.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    def fake_get(url: str, **kwargs):
        assert url == "https://api.deepseek.com/models"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-chat", "owned_by": "deepseek"},
                    {"id": "deepseek-reasoner", "context_window": 65536},
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("blackcat.webui.settings_api.httpx.get", fake_get)

    payload = provider_models_payload({"provider": ["deepseek"]})

    assert payload["status"] == "available"
    assert payload["catalog_kind"] == "official"
    assert payload["model_count"] == 2
    assert payload["models"][0]["id"] == "deepseek-chat"
    assert payload["models"][1]["context_window"] == 65536


@pytest.mark.parametrize(
    ("api_base", "expected_url"),
    [
        ("https://api.minimaxi.com/anthropic", "https://api.minimaxi.com/anthropic/v1/models"),
        ("https://api.minimaxi.com/anthropic/v1", "https://api.minimaxi.com/anthropic/v1/models"),
    ],
)
def test_provider_models_payload_fetches_minimax_anthropic_models(
    api_base: str,
    expected_url: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.minimax_anthropic.api_key = "sk-test"
    config.providers.minimax_anthropic.api_base = api_base
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    def fake_get(url: str, **kwargs):
        assert url == expected_url
        assert kwargs["headers"]["X-Api-Key"] == "sk-test"
        assert "Authorization" not in kwargs["headers"]
        return httpx.Response(
            200,
            json={"data": [{"id": "MiniMax-M2.7-highspeed"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("blackcat.webui.settings_api.httpx.get", fake_get)

    payload = provider_models_payload({"provider": ["minimax_anthropic"]})

    assert payload["status"] == "available"
    assert payload["catalog_kind"] == "official"
    assert payload["models"] == [
        {
            "id": "MiniMax-M2.7-highspeed",
            "label": None,
            "owned_by": None,
            "context_window": None,
        }
    ]


def test_provider_models_payload_requires_gateway_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = provider_models_payload({"provider": ["openrouter"]})

    assert payload["status"] == "not_configured"
    assert payload["models"] == []


def test_create_model_configuration_accepts_configured_oauth_provider(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "blackcat.webui.settings_api._oauth_provider_status",
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


# ---------------------------------------------------------------------------
# Azure OpenAI: settings contract for static-key vs AAD (DefaultAzureCredential)
# ---------------------------------------------------------------------------


def test_settings_payload_azure_openai_with_api_key_is_configured(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static-key mode: api_key + api_base both set -> configured."""
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.azure_openai.api_key = "k"
    config.providers.azure_openai.api_base = "https://r.openai.azure.com"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = settings_payload()
    azure = next(row for row in payload["providers"] if row["name"] == "azure_openai")

    assert azure["configured"] is True
    assert azure["api_key_required"] is False
    assert azure["auth_type"] == "api_key"
    assert azure["api_base"] == "https://r.openai.azure.com"


def test_settings_payload_azure_openai_aad_mode_is_configured(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AAD mode: only api_base set (no api_key) -> still configured."""
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.azure_openai.api_base = "https://r.openai.azure.com"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = settings_payload()
    azure = next(row for row in payload["providers"] if row["name"] == "azure_openai")

    assert azure["configured"] is True
    assert azure["api_key_required"] is False
    assert azure["api_base"] == "https://r.openai.azure.com"
    assert azure["api_key_hint"] is None


def test_settings_payload_azure_openai_missing_base_not_configured(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api_key alone (no api_base) is NOT a working config -> not configured."""
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.azure_openai.api_key = "k"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = settings_payload()
    azure = next(row for row in payload["providers"] if row["name"] == "azure_openai")

    assert azure["configured"] is False


def test_create_model_configuration_accepts_azure_openai_aad_mode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider-validation accepts azure_openai with only api_base (AAD mode)."""
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.azure_openai.api_base = "https://r.openai.azure.com"
    save_config(config, config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    payload = create_model_configuration(
        {
            "label": ["Azure AAD"],
            "provider": ["azure_openai"],
            "model": ["my-deployment"],
        }
    )

    assert payload["agent"]["model_preset"] == "azure-aad"
    saved = load_config(config_path)
    assert saved.model_presets["azure-aad"].provider == "azure_openai"
    assert saved.model_presets["azure-aad"].model == "my-deployment"


def test_create_model_configuration_rejects_azure_openai_without_base(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """azure_openai without api_base must still be rejected as not configured."""
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("blackcat.config.loader._current_config_path", config_path)

    with pytest.raises(WebUISettingsError, match="provider is not configured"):
        create_model_configuration(
            {
                "label": ["Azure"],
                "provider": ["azure_openai"],
                "model": ["my-deployment"],
            }
        )


def test_azure_openai_spec_no_longer_requires_api_key() -> None:
    """Contract guard: api_key is optional for azure_openai (AAD fallback)."""
    from blackcat.webui.settings_api import _provider_requires_api_key

    spec = find_by_name("azure_openai")
    assert spec is not None
    assert _provider_requires_api_key(spec) is False
