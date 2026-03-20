"""Provider Registry — re-exports from config layer (boundary fix — LAN-54).

The canonical definitions now live in ``nanobot.config.providers_registry``
so that ``config/schema.py`` can import them without violating the rule that
``config/`` must never import from ``providers/``.

All existing importers of ``nanobot.providers.registry`` continue to work
unchanged via the re-exports below.
"""

from __future__ import annotations

# Re-export everything from config layer (boundary fix — LAN-54)
from nanobot.config.providers_registry import (  # noqa: F401
    PROVIDERS,
    ProviderSpec,
    find_by_model,
    find_by_name,
    find_gateway,
)

__all__ = ["ProviderSpec", "PROVIDERS", "find_by_model", "find_gateway", "find_by_name"]
