from unittest.mock import patch

from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.registry import load_channel_plugin
from nanobot.config.schema import Config


def test_websocket_plugin_exposes_config_model() -> None:
    config_model = load_channel_plugin("websocket").load_config_model()

    assert config_model is not None
    assert config_model.__name__ == "WebSocketConfig"


def test_matrix_config_model_loads_without_runtime_dependencies() -> None:
    config_model = load_channel_plugin("matrix").load_config_model()

    assert config_model is not None
    assert config_model.__module__ == "nanobot.channels.matrix.config"


def test_channel_status_exposes_safe_validation_detail() -> None:
    config = Config.model_validate(
        {"channels": {"websocket": {"enabled": True, "path": "missing-slash"}}}
    )

    manager = ChannelManager(config, MessageBus(), webui_static_dist=False)

    error = manager.get_status()["websocket"]["error"]
    assert "channels.websocket.path" in error
    assert 'Path must start with "/".' in error
    assert "input_value" not in error
    assert "errors.pydantic.dev" not in error


def test_channel_validation_log_does_not_expose_invalid_secret() -> None:
    secret = "should-never-appear"
    config = Config.model_validate(
        {"channels": {"websocket": {"enabled": True, "token": [secret]}}}
    )

    with patch("nanobot.channels.manager.logger.warning") as warning:
        ChannelManager(config, MessageBus(), webui_static_dist=False)

    logged = " ".join(str(arg) for call in warning.call_args_list for arg in call.args)
    assert "Invalid channel configuration" in logged
    assert secret not in logged
    assert "input_value" not in logged
