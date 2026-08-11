from __future__ import annotations

from typing import Any

from nanobot.config.schema import Config
from nanobot.webui.settings_models import (
    model_settings_payload,
    update_agent_model_settings,
    update_provider_settings,
)


def _oauth_status(_spec: Any) -> dict[str, Any]:
    return {
        "configured": False,
        "account": None,
        "expires_at": None,
        "login_supported": True,
    }


def test_model_domain_owns_dto_and_config_updates() -> None:
    config = Config()
    config.providers.openrouter.api_key = "sk-before"

    agent_changed = update_agent_model_settings(
        config,
        {
            "model": ["openai/gpt-5.4"],
            "provider": ["openrouter"],
            "context_window_tokens": ["200000"],
        },
        oauth_status=_oauth_status,
    )
    provider_changed, restart_required = update_provider_settings(
        config,
        {
            "provider": ["openrouter"],
            "api_key": ["sk-after"],
        },
    )
    payload = model_settings_payload(config, oauth_status=_oauth_status)

    assert agent_changed is True
    assert provider_changed is True
    assert restart_required is False
    assert config.agents.defaults.model == "openai/gpt-5.4"
    assert config.agents.defaults.provider == "openrouter"
    assert config.agents.defaults.context_window_tokens == 200_000
    assert config.providers.openrouter.api_key == "sk-after"
    assert set(payload) == {
        "agent",
        "model_presets",
        "model_call_order",
        "model_call_order_editable",
        "providers",
    }
    assert payload["agent"]["model"] == "openai/gpt-5.4"
