import pytest

from nanobot.config.schema import Config, GatewayConfig


def test_gateway_restart_mode_accepts_camel_alias():
    config = Config.model_validate({"gateway": {"restartMode": "exit"}})

    assert config.gateway.restart_mode == "exit"
    assert config.model_dump(by_alias=True)["gateway"]["restartMode"] == "exit"


def test_gateway_restart_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        GatewayConfig(restart_mode="service")


def test_heartbeat_isolated_session_accepts_aliases_and_serializes_camel_case():
    assert Config().gateway.heartbeat.isolated_session is True

    for key in ("isolatedSession", "isolated_session"):
        config = Config.model_validate({"gateway": {"heartbeat": {key: False}}})

        assert config.gateway.heartbeat.isolated_session is False
        heartbeat = config.model_dump(by_alias=True)["gateway"]["heartbeat"]
        assert heartbeat["isolatedSession"] is False
        assert "isolated_session" not in heartbeat
