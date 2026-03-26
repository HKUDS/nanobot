"""Connector lifecycle manager."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from nanobot.config.schema import Config, DockerConnectorConfig, MCPServerConfig
from nanobot.connectors.base import BaseConnector
from nanobot.connectors.docker import DockerConnector


class ConnectorManager:
    """Manage external connector runtimes and their MCP endpoints."""

    def __init__(self, config: Config):
        self.config = config
        self.workspace = config.workspace_path
        self.connectors: dict[str, BaseConnector] = {}
        self._init_connectors()

    def _iter_raw_configs(self) -> dict[str, dict[str, Any]]:
        raw = getattr(self.config.connectors, "model_extra", None) or {}
        return {
            name: section
            for name, section in raw.items()
            if isinstance(section, dict)
        }

    def _init_connectors(self) -> None:
        for name, raw in self._iter_raw_configs().items():
            if not raw.get("enabled", False):
                continue

            connector_type = str(raw.get("type", "docker")).strip().lower()
            try:
                if connector_type == "docker":
                    cfg = DockerConnectorConfig.model_validate(raw)
                    self.connectors[name] = DockerConnector(name, cfg, self.workspace)
                    logger.info("Connector '{}' enabled", name)
                else:
                    logger.warning("Unsupported connector type '{}' for '{}'", connector_type, name)
            except Exception as exc:
                logger.warning("Connector '{}' not available: {}", name, exc)

    async def start_all(self) -> None:
        for name, connector in self.connectors.items():
            logger.info("Starting connector '{}'...", name)
            await asyncio.to_thread(connector.start)

    async def stop_all(self, *, force: bool = False) -> None:
        for name, connector in reversed(list(self.connectors.items())):
            try:
                await asyncio.to_thread(connector.stop, force)
            except Exception as exc:
                logger.warning("Failed to stop connector '{}': {}", name, exc)

    def merged_mcp_servers(self, base: dict[str, MCPServerConfig]) -> dict[str, MCPServerConfig]:
        merged = dict(base)
        for connector_name, connector in self.connectors.items():
            for server_name, server_cfg in connector.mcp_servers().items():
                target_name = server_name
                if target_name in merged:
                    target_name = f"{connector_name}_{server_name}"
                if target_name in merged:
                    target_name = f"connector_{connector_name}_{server_name}"
                merged[target_name] = server_cfg
        return merged

    def status(self) -> dict[str, dict[str, Any]]:
        return {
            name: connector.status()
            for name, connector in self.connectors.items()
        }

    @property
    def enabled_connectors(self) -> list[str]:
        return list(self.connectors.keys())
