"""Public provider plugin surface for nanobot."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from nanobot.providers.base import GenerationSettings
from nanobot.providers.registry import (
    ProviderFactory,
    ProviderSpec,
    discover_provider_plugins,
    find_by_name,
    get_provider_factory,
    get_provider_specs,
    normalize_provider_name,
    register_provider_factory,
    register_provider_spec,
    unregister_provider_factory,
    unregister_provider_spec,
)


def apply_generation_defaults(provider: Any, defaults: Any) -> Any:
    """Apply nanobot's generation defaults to a provider instance."""
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=getattr(defaults, "reasoning_effort", None),
    )
    return provider


def create_provider(config: Any, *, native_factory: Callable[[Any], Any]) -> Any:
    """Create a provider via plugin factory when available, else use native logic."""
    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    factory = get_provider_factory(provider_name)
    if factory is None:
        return native_factory(config)

    provider_config = config.get_provider(model)
    spec = find_by_name(provider_name)
    try:
        provider = factory(config=provider_config, model=model, spec=spec)
    except Exception:
        logger.exception(
            "Plugin provider factory '{}' failed; falling back to native provider path",
            provider_name,
        )
        return native_factory(config)

    return apply_generation_defaults(provider, config.agents.defaults)


__all__ = [
    "ProviderFactory",
    "ProviderSpec",
    "apply_generation_defaults",
    "create_provider",
    "discover_provider_plugins",
    "find_by_name",
    "get_provider_factory",
    "get_provider_specs",
    "normalize_provider_name",
    "register_provider_factory",
    "register_provider_spec",
    "unregister_provider_factory",
    "unregister_provider_spec",
]