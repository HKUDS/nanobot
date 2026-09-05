import pytest

from nanobot.config.schema import Config, GatewayConfig


def test_gateway_restart_mode_accepts_camel_alias():
    config = Config.model_validate({"gateway": {"restartMode": "exit"}})

    assert config.gateway.restart_mode == "exit"
    assert config.model_dump(by_alias=True)["gateway"]["restartMode"] == "exit"


def test_gateway_restart_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        GatewayConfig(restart_mode="service")
