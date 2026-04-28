import pytest
from pydantic import ValidationError

from nanobot.config.schema import AgentDefaults, Config


def test_failover_defaults_are_disabled_until_fallback_models_configured() -> None:
    defaults = AgentDefaults()

    assert defaults.fallback_models == []
    assert defaults.failover.enabled is True
    assert defaults.failover.cooldown_seconds == 120.0
    assert defaults.failover.max_switches_per_turn == 0
    assert defaults.failover.failover_on_quota is False


def test_fallback_models_and_failover_accept_camel_case_aliases() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "fallbackModels": ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4-5"],
                "failover": {
                    "cooldownSeconds": 30,
                    "maxSwitchesPerTurn": 1,
                    "failoverOnQuota": True,
                },
            }
        }
    })

    defaults = config.agents.defaults
    assert defaults.fallback_models == [
        "openai/gpt-4.1-mini",
        "anthropic/claude-sonnet-4-5",
    ]
    assert defaults.failover.cooldown_seconds == 30
    assert defaults.failover.max_switches_per_turn == 1
    assert defaults.failover.failover_on_quota is True


def test_invalid_failover_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({
            "agents": {
                "defaults": {
                    "fallbackModels": ["openai/gpt-4.1-mini"],
                    "failover": {"cooldownSeconds": -1},
                }
            }
        })

    with pytest.raises(ValidationError):
        Config.model_validate({
            "agents": {
                "defaults": {
                    "fallbackModels": ["openai/gpt-4.1-mini"],
                    "failover": {"maxSwitchesPerTurn": -1},
                }
            }
        })
