"""Auto-discovery for built-in image generation provider modules.

Mirrors the pkgutil-scan pattern used by ``nanobot/channels/registry.py``.
Each provider module in this package that defines an
:class:`ImageGenerationProvider` subclass with a non-empty ``provider_name``
is registered automatically on first access.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from loguru import logger

from nanobot.providers.image_generation.base import ImageGenerationProvider

_INTERNAL = frozenset({"base", "registry"})

_PROVIDERS: dict[str, type[ImageGenerationProvider]] | None = None


def _discover_builtin() -> dict[str, type[ImageGenerationProvider]]:
    """Scan this package and return all built-in image gen provider classes."""
    import nanobot.providers.image_generation as pkg

    found: dict[str, type[ImageGenerationProvider]] = {}
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or name in _INTERNAL:
            continue
        try:
            mod = importlib.import_module(f"{pkg.__name__}.{name}")
        except Exception as exc:
            logger.warning("Failed to import image generation provider module '{}': {}", name, exc)
            continue
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (
                isinstance(obj, type)
                and issubclass(obj, ImageGenerationProvider)
                and obj is not ImageGenerationProvider
            ):
                provider_name = getattr(obj, "provider_name", "")
                if not provider_name:
                    continue
                found.setdefault(provider_name, obj)
    return found


def _ensure_providers() -> dict[str, type[ImageGenerationProvider]]:
    global _PROVIDERS
    if _PROVIDERS is None:
        _PROVIDERS = _discover_builtin()
    return _PROVIDERS


def register_image_gen_provider(cls: type[ImageGenerationProvider]) -> None:
    """Register an image generation provider class.

    Built-in providers are auto-discovered on first lookup, so this entry point
    is only needed for external code that wants to add a custom provider at
    runtime (e.g., from a third-party package's import side-effect).
    """
    name = cls.provider_name
    if not name:
        raise ValueError(f"{cls.__name__} must set provider_name")
    _ensure_providers()[name] = cls


def get_image_gen_provider(name: str) -> type[ImageGenerationProvider] | None:
    """Return the provider class for *name*, or None if not registered."""
    return _ensure_providers().get(name)


def image_gen_provider_names() -> tuple[str, ...]:
    """Return registered image generation provider names in registry order."""
    return tuple(_ensure_providers())


def image_gen_provider_configs(config: Any) -> dict[str, Any]:
    """Return the ``providers.<name>`` config for every registered provider."""
    providers_cfg = config.providers
    return {
        name: pc
        for name in _ensure_providers()
        if (pc := getattr(providers_cfg, name, None)) is not None
    }
