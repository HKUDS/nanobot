from pathlib import Path
from unittest.mock import patch

from nanobot.cli.commands import (
    _bridge_socket_target,
    _get_local_whatsapp_bridge_launch_spec,
)
from nanobot.config.schema import Config


def test_bridge_socket_target_only_accepts_local_ws_urls():
    assert _bridge_socket_target("ws://localhost:3001") == ("localhost", 3001)
    assert _bridge_socket_target("wss://127.0.0.1") == ("127.0.0.1", 443)
    assert _bridge_socket_target("ws://example.com:3001") is None
    assert _bridge_socket_target("http://localhost:3001") is None


def test_local_whatsapp_bridge_launch_spec_uses_bridge_port_and_token(tmp_path: Path):
    config = Config()
    config.channels.whatsapp.enabled = True
    config.channels.whatsapp.bridge_url = "ws://localhost:3010"
    config.channels.whatsapp.bridge_token = "secret"

    with patch("nanobot.cli.commands._get_bridge_dir", return_value=tmp_path):
        bridge_dir, env = _get_local_whatsapp_bridge_launch_spec(config) or (None, None)

    assert bridge_dir == tmp_path
    assert env is not None
    assert env["BRIDGE_PORT"] == "3010"
    assert env["BRIDGE_TOKEN"] == "secret"


def test_local_whatsapp_bridge_launch_spec_skips_remote_bridge():
    config = Config()
    config.channels.whatsapp.enabled = True
    config.channels.whatsapp.bridge_url = "ws://bridge.example.com:3010"

    assert _get_local_whatsapp_bridge_launch_spec(config) is None
