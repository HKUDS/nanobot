"""Base interface for external runtime connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from nanobot.config.schema import MCPServerConfig


class BaseConnector(ABC):
    """Abstract lifecycle for an external connector runtime."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def start(self) -> None:
        """Start the connector runtime."""

    @abstractmethod
    def stop(self, force: bool = False) -> None:
        """Stop the connector runtime."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Return connector runtime status."""

    @abstractmethod
    def mcp_servers(self) -> dict[str, MCPServerConfig]:
        """Return MCP servers exported by this connector."""
