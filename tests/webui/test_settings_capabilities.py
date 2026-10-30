from __future__ import annotations

from typing import Any

import pytest

from nanobot.config.schema import Config
from nanobot.webui.settings_capabilities import (
    capability_settings_payload,
    update_api_settings,
    update_image_generation_settings,
    update_network_safety_settings,
    update_transcription_settings,
    update_web_search_settings,
)
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_models import create_provider_settings, update_provider_settings


def test_dynamic_image_provider_selection_and_private_overrides():
    config = Config()
    name = create_provider_settings(config, {
        "name": ["SenseNova"], "apiBase": ["https://images.test/v1"],
    })
    assert update_image_generation_settings(config, {
        "provider": [name], "model": ["image-model"], "enabled": ["true"],
        "extraHeaders": ['{"X-Api-Key":"private-key"}'],
        "extraBody": ['{"watermark":false}'],
    }, oauth_status=_oauth_status)
    payload = capability_settings_payload(config, oauth_status=_oauth_status)["image_generation"]
    assert payload["provider"] == name
    assert payload["extra_headers"] == {"X-Api-Key": "••••••••"}
    assert "private-key" not in str(payload)
    row = next(row for row in payload["providers"] if row["name"] == name)
    assert row["label"] == "SenseNova" and row["configured"] and row["uses_images_api"]
    changed, reload_needed = update_provider_settings(config, {
        "provider": [name], "apiBase": ["https://updated.test/v1"],
    })
    assert changed and reload_needed
    update_image_generation_settings(config, {
        "extra_headers": ['{"X-Api-Key":"••••••••","X-Route":"images"}'],
    }, oauth_status=_oauth_status)
    assert config.tools.image_generation.extra_headers["X-Api-Key"] == "private-key"
    with pytest.raises(WebUISettingsError, match="JSON object"):
        update_image_generation_settings(config, {"extra_body": ["[]"]}, oauth_status=_oauth_status)
    config.providers.openai.api_key = "fixture"
    update_image_generation_settings(config, {"provider": ["openai"]}, oauth_status=_oauth_status)
    assert config.tools.image_generation.extra_headers is None
    assert config.tools.image_generation.extra_body is None


def test_image_provider_keeps_dynamic_id_case_and_rejects_missing_connection():
    config = Config.model_validate({"providers": {"CompanyGateway": {"apiBase": "https://images.test/v1"}}})
    update_image_generation_settings(config, {
        "provider": ["CompanyGateway"], "model": ["image"], "enabled": ["true"],
    }, oauth_status=_oauth_status)
    assert config.tools.image_generation.provider == "CompanyGateway"
    with pytest.raises(WebUISettingsError, match="unknown image generation provider"):
        update_image_generation_settings(config, {"provider": ["missing"]}, oauth_status=_oauth_status)


def _oauth_status(_spec: Any) -> dict[str, Any]:
    return {"configured": False}


def test_capability_domain_updates_representative_settings() -> None:
    config = Config()
    config.providers.openrouter.api_key = "sk-test"

    web_changed, web_restart = update_web_search_settings(
        config,
        {
            "provider": ["duckduckgo"],
            "max_results": ["7"],
            "use_jina_reader": ["false"],
        },
    )
    update_api_settings(
        config,
        {"host": ["127.0.0.2"], "port": ["8900"], "timeout": ["90"]},
    )
    image_changed = update_image_generation_settings(
        config,
        {"enabled": ["true"], "provider": ["openrouter"]},
        oauth_status=_oauth_status,
    )
    transcription_changed = update_transcription_settings(
        config,
        {"provider": ["openrouter"], "model": ["openai/whisper-large-v3"]},
    )
    network_changed, access_mode = update_network_safety_settings(
        config,
        {
            "webui_allow_local_service_access": ["false"],
            "webui_default_access_mode": ["restricted"],
        },
    )
    payload = capability_settings_payload(config, oauth_status=_oauth_status)

    assert (web_changed, web_restart) == (True, True)
    assert image_changed is True
    assert transcription_changed is True
    assert (network_changed, access_mode) == (True, "default")
    assert payload["web_search"]["max_results"] == 7
    assert payload["api"]["host"] == "127.0.0.2"
    assert payload["api"]["port"] == 8900
    assert payload["image_generation"]["enabled"] is True
    assert payload["transcription"]["provider"] == "openrouter"
