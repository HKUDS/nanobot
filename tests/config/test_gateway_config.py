import pytest

from nanobot.config.schema import Config, GatewayConfig


def test_gateway_restart_mode_accepts_camel_alias():
    config = Config.model_validate({"gateway": {"restartMode": "exit"}})

    assert config.gateway.restart_mode == "exit"
    assert config.model_dump(by_alias=True)["gateway"]["restartMode"] == "exit"


def test_gateway_restart_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        GatewayConfig(restart_mode="service")


def test_heartbeat_ignores_removed_retention_limit():
    config = Config.model_validate(
        {"gateway": {"heartbeat": {"keepRecentMessages": 8}}}
    )

    heartbeat = config.model_dump(by_alias=True)["gateway"]["heartbeat"]
    assert "keepRecentMessages" not in heartbeat


def test_direct_delivery_accepts_camel_case_and_normalizes_path():
    config = Config.model_validate({
        "gateway": {
            "directDelivery": {
                "enabled": True,
                "path": "hooks/deliver/",
                "secret": "secret",
                "channel": "telegram",
                "chatId": "123",
                "maxAgeSeconds": 120,
            }
        }
    })

    delivery = config.gateway.direct_delivery
    assert delivery.path == "/hooks/deliver"
    assert delivery.chat_id == "123"
    assert delivery.max_age_seconds == 120
    assert config.model_dump(by_alias=True)["gateway"]["directDelivery"]["chatId"] == "123"


def test_enabled_direct_delivery_requires_secret_and_target():
    with pytest.raises(ValueError, match="secret, channel, and chat_id"):
        Config.model_validate({"gateway": {"directDelivery": {"enabled": True}}})
