from __future__ import annotations

import importlib
import socket
from pathlib import Path


def test_package_imports_without_runtime_config(monkeypatch):
    forbidden_env = [
        "CRM_GRAPHQL_ENDPOINT",
        "CRM_GRAPHQL_TOKEN",
        "NANOBOT_CRM_GRAPHQL_ENDPOINT",
        "NANOBOT_CRM_GRAPHQL_TOKEN",
    ]
    for name in forbidden_env:
        monkeypatch.delenv(name, raising=False)

    package = importlib.import_module("crm_mcp_server")
    server = importlib.import_module("crm_mcp_server.server")

    assert package.__version__
    assert server.get_server_metadata()["name"] == "crm-mcp-server"


def test_skeleton_start_does_not_require_env_file_or_network(monkeypatch):
    opened_paths: list[str] = []
    connected_addresses: list[object] = []

    original_open = Path.open

    def tracking_open(self: Path, *args, **kwargs):
        opened_paths.append(str(self))
        if self.name == ".env.nanobot":
            raise AssertionError("skeleton must not read .env.nanobot")
        return original_open(self, *args, **kwargs)

    def fake_connect(self: socket.socket, address):
        connected_addresses.append(address)
        raise AssertionError("skeleton must not open network connections")

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    from crm_mcp_server.server import create_server_skeleton

    skeleton = create_server_skeleton()

    assert skeleton.metadata.name == "crm-mcp-server"
    assert skeleton.runtime.real_crm_access_enabled is False
    assert not connected_addresses
    assert not any(path.endswith(".env.nanobot") for path in opened_paths)


def test_runtime_defaults_disable_real_crm_access():
    from crm_mcp_server.server import create_server_skeleton

    skeleton = create_server_skeleton()

    runtime = skeleton.runtime

    assert runtime.real_crm_access_enabled is False
    assert runtime.requires_endpoint is False
    assert runtime.requires_token is False
    assert runtime.network_enabled is False
