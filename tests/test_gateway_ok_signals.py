from nanobot.config.schema import Config


def test_gateway_ok_signal_config_accepts_camel_case() -> None:
    config = Config.model_validate({
        "gateway": {
            "heartbeat": {
                "okSignal": "HB_DONE",
                "sendOkSignalMessages": False,
            },
            "cron": {
                "okSignal": "CRON_DONE",
                "sendOkSignalMessages": False,
            },
        }
    })

    assert config.gateway.heartbeat.ok_signal == "HB_DONE"
    assert config.gateway.heartbeat.send_ok_signal_messages is False
    assert config.gateway.cron.ok_signal == "CRON_DONE"
    assert config.gateway.cron.send_ok_signal_messages is False
