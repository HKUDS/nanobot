"""Provider plugin loading helpers."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import Config, ProviderConfig
    from nanobot.providers.base import LLMProvider

ProviderFactory = Callable[..., "LLMProvider"]


def _iter_entry_points(group: str) -> list[Any]:
    """Return entry points for a group, compatible with Python 3.11+ APIs."""
    entry_points = importlib_metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=group))
    return list(entry_points.get(group, []))


def load_provider_factories() -> dict[str, ProviderFactory]:
    """Load plugin provider factories from ``nanobot.provider_factories`` entry points."""
    factories: dict[str, ProviderFactory] = {}
    for ep in _iter_entry_points("nanobot.provider_factories"):
        try:
            factory = ep.load()
        except Exception as exc:
            logger.warning("Failed loading provider factory plugin {}: {}", ep.name, exc)
            continue

        if not callable(factory):
            logger.warning("Ignore provider factory plugin {}: object is not callable", ep.name)
            continue

        name = ep.name.replace("-", "_")
        if name in factories:
            logger.warning("Ignore provider factory plugin {}: duplicate provider name", name)
            continue
        factories[name] = factory
    return factories


def get_provider_factory(name: str | None) -> ProviderFactory | None:
    """Get provider factory by provider name (normalized to snake_case)."""
    if not name:
        return None
    normalized = name.replace("-", "_")
    return load_provider_factories().get(normalized)


def create_provider_by_factory(
    factory: ProviderFactory,
    *,
    config: "Config",
    model: str,
    provider_name: str | None,
    provider_config: "ProviderConfig | None",
) -> "LLMProvider":
    """Create provider from plugin factory using a stable keyword contract."""
    return factory(
        config=config,
        model=model,
        provider_name=provider_name,
        provider_config=provider_config,
    )
