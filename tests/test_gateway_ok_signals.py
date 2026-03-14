from nanobot.cli.commands import _should_publish_background_response
from nanobot.config.schema import Config


def test_background_ok_signal_suppresses_exact_match_only() -> None:
    assert _should_publish_background_response(
        "CRON_OK",
        ok_signal="CRON_OK",
        send_ok_signal_messages=False,
    ) is False
    assert _should_publish_background_response(
        "  CRON_OK \n",
        ok_signal="CRON_OK",
        send_ok_signal_messages=False,
    ) is False
    assert _should_publish_background_response(
        "CRON_OK done",
        ok_signal="CRON_OK",
        send_ok_signal_messages=False,
    ) is True


def test_background_ok_signal_can_be_posted_raw() -> None:
    assert _should_publish_background_response(
        "HEARTBEAT_OK",
        ok_signal="HEARTBEAT_OK",
        send_ok_signal_messages=True,
    ) is True
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
