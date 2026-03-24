"""Honcho client initialization and configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from honcho import Honcho


@dataclass
class HonchoClientConfig:
    """Configuration for Honcho client."""

    workspace_id: str = "nanobot"
    api_key: str | None = None
    environment: str = "production"

    @classmethod
    def from_env(cls, workspace_id: str = "nanobot") -> HonchoClientConfig:
        """Create config from environment variables."""
        return cls(
            workspace_id=workspace_id,
            api_key=os.environ.get("HONCHO_API_KEY"),
            environment=os.environ.get("HONCHO_ENVIRONMENT", "production"),
        )


_honcho_client: Honcho | None = None


def get_honcho_client(config: HonchoClientConfig | None = None) -> Honcho:
    """
    Get or create the Honcho client singleton.

    Args:
        config: Optional config. If not provided, uses environment variables.

    Returns:
        Configured Honcho client.

    Raises:
        ValueError: If HONCHO_API_KEY is not set.
    """
    global _honcho_client

    if _honcho_client is not None:
        return _honcho_client

    if config is None:
        config = HonchoClientConfig.from_env()

    if not config.api_key:
        raise ValueError(
            "HONCHO_API_KEY environment variable is required. "
            "Get an API key from https://app.honcho.dev"
        )

    try:
        from honcho import Honcho
    except ImportError:
        raise ImportError(
            "honcho-ai is required for Honcho integration. "
            "Install it with: nanobot honcho enable --api-key YOUR_KEY"
        )

    logger.info(f"Initializing Honcho client (workspace: {config.workspace_id})")

    _honcho_client = Honcho(
        workspace_id=config.workspace_id,
        api_key=config.api_key,
        environment=config.environment,
    )

    return _honcho_client


def reset_honcho_client() -> None:
    """Reset the Honcho client singleton (useful for testing)."""
    global _honcho_client
    _honcho_client = None
