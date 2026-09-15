import pytest

from nanobot.config.schema import Config, GatewayConfig


def test_gateway_restart_mode_accepts_camel_alias():
    config = Config.model_validate({"gateway": {"restartMode": "exit"}})

    assert config.gateway.restart_mode == "exit"
    assert config.model_dump(by_alias=True)["gateway"]["restartMode"] == "exit"


def test_gateway_restart_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        GatewayConfig(restart_mode="service")


def test_heartbeat_model_override_accepts_aliases_and_serializes_camel_case():
    for key in ("modelOverride", "model", "model_override"):
        config = Config.model_validate(
            {"gateway": {"heartbeat": {key: "openai/gpt-4o-mini"}}}
        )

        assert config.gateway.heartbeat.model_override == "openai/gpt-4o-mini"
        heartbeat = config.model_dump(by_alias=True)["gateway"]["heartbeat"]
        assert heartbeat["modelOverride"] == "openai/gpt-4o-mini"
        assert "model_override" not in heartbeat
