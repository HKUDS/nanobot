from __future__ import annotations

from pathlib import Path

from nanobot.config.schema import Config
from nanobot.connectors.docker import DockerConnector
from nanobot.connectors.manager import ConnectorManager


def test_connector_manager_merges_prefixed_mcp_servers() -> None:
    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": "/tmp/workspace"}},
            "connectors": {
                "weather": {
                    "enabled": True,
                    "type": "docker",
                    "composeFile": "/tmp/workspace/connectors/weather/compose.yml",
                    "services": ["weather-mcp"],
                    "mcpServers": {
                        "api": {
                            "url": "http://127.0.0.1:9010/mcp",
                            "type": "streamableHttp",
                        }
                    },
                }
            },
            "tools": {
                "mcpServers": {
                    "api": {
                        "url": "http://127.0.0.1:9020/mcp",
                        "type": "streamableHttp",
                    }
                }
            },
        }
    )

    manager = ConnectorManager(config)
    merged = manager.merged_mcp_servers(config.tools.mcp_servers)

    assert "api" in merged
    assert "weather_api" in merged
    assert merged["weather_api"].url == "http://127.0.0.1:9010/mcp"


def test_docker_connector_expands_workspace_tokens(tmp_path: Path) -> None:
    compose_file = tmp_path / "connector" / "compose.yml"
    compose_file.parent.mkdir(parents=True)
    compose_file.write_text("services: {}\n", encoding="utf-8")

    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(tmp_path)}},
            "connectors": {
                "demo": {
                    "enabled": True,
                    "type": "docker",
                    "composeFile": str(compose_file),
                    "env": {
                        "WORKDIR": "${WORKSPACE}/data",
                        "NAME": "${CONNECTOR_NAME}",
                    },
                }
            },
        }
    )
    manager = ConnectorManager(config)
    connector = manager.connectors["demo"]
    assert isinstance(connector, DockerConnector)

    env = connector._command_env()
    assert env["WORKDIR"] == f"{tmp_path}/data"
    assert env["NAME"] == "demo"
