import pytest
from pydantic import ValidationError

from nanobot.config.schema import Config


def test_heartbeat_config_defaults() -> None:
    cfg = Config()

    assert cfg.gateway.heartbeat.enabled is True
    assert cfg.gateway.heartbeat.interval_s == 30 * 60
    assert cfg.gateway.heartbeat.model == ""


def test_heartbeat_config_accepts_custom_model_and_interval() -> None:
    cfg = Config.model_validate(
        {
            "gateway": {
                "heartbeat": {
                    "enabled": True,
                    "intervalS": 120,
                    "model": "openai/gpt-4o-mini",
                }
            }
        }
    )

    assert cfg.gateway.heartbeat.enabled is True
    assert cfg.gateway.heartbeat.interval_s == 120
    assert cfg.gateway.heartbeat.model == "openai/gpt-4o-mini"


def test_heartbeat_config_rejects_non_positive_interval() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "gateway": {
                    "heartbeat": {
                        "interval_s": 0,
                    }
                }
            }
        )
