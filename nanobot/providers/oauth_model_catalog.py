"""Dispatch OAuth model discovery to the owning provider."""

from __future__ import annotations

from nanobot.providers.oauth_catalog_cache import (
    CatalogErrorKind as CatalogErrorKind,
)
from nanobot.providers.oauth_catalog_cache import (
    CatalogSource as CatalogSource,
)
from nanobot.providers.oauth_catalog_cache import (
    OAuthCatalogAuthRequiredError as OAuthCatalogAuthRequiredError,
)
from nanobot.providers.oauth_catalog_cache import (
    OAuthModelCatalog as OAuthModelCatalog,
)
from nanobot.providers.oauth_catalog_cache import (
    OAuthModelCatalogSnapshot as OAuthModelCatalogSnapshot,
)
from nanobot.providers.oauth_catalog_cache import (
    oauth_catalog_auth_rejected as oauth_catalog_auth_rejected,
)


def get_oauth_model_catalog(
    provider_name: str,
    *,
    proxy: str | None = None,
    refresh: bool = False,
) -> OAuthModelCatalogSnapshot:
    """Discover models through the owning provider module."""
    if provider_name == "openai_codex":
        from nanobot.providers.openai_codex_provider import get_openai_codex_model_catalog

        return get_openai_codex_model_catalog(proxy, refresh=refresh)
    if provider_name == "xai_grok":
        from nanobot.providers.xai_grok_provider import get_xai_grok_model_catalog

        return get_xai_grok_model_catalog(proxy, refresh=refresh)
    if provider_name == "github_copilot":
        from nanobot.providers.github_copilot_provider import get_github_copilot_model_catalog

        return get_github_copilot_model_catalog(proxy, refresh=refresh)
    raise ValueError(f"OAuth model discovery is not available for {provider_name}")


def invalidate_oauth_model_catalog(provider_name: str) -> None:
    """Invalidate provider discovery after its OAuth identity changes."""
    if provider_name == "openai_codex":
        from nanobot.providers.openai_codex_provider import (
            invalidate_openai_codex_model_catalog,
        )

        invalidate_openai_codex_model_catalog()
    elif provider_name == "xai_grok":
        from nanobot.providers.xai_grok_provider import invalidate_xai_grok_model_catalog

        invalidate_xai_grok_model_catalog()
    elif provider_name == "github_copilot":
        from nanobot.providers.github_copilot_provider import (
            invalidate_github_copilot_model_catalog,
        )

        invalidate_github_copilot_model_catalog()
