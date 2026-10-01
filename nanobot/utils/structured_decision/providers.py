"""Provider profiles and decision endpoint resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from .errors import UnsupportedDecisionProtocolError, UnsupportedDecisionProviderError

if TYPE_CHECKING:
    from nanobot.config.schema import Config


@dataclass(frozen=True)
class DecisionProviderProfile:
    name: str
    base_url: str
    route: str
    api_key_env: str | None
    protocols: tuple[str, ...]
    requires_api_key: bool = True


@dataclass(frozen=True)
class DecisionProviderSettings:
    name: str
    protocol: str
    endpoint_url: str
    api_key: str | None = field(repr=False)
    proxy: str | None
    requires_api_key: bool


_PROVIDER_PROFILES = {
    "openrouter": DecisionProviderProfile(
        name="openrouter",
        base_url="https://openrouter.ai/api",
        route="/alpha/decisions",
        api_key_env="OPENROUTER_API_KEY",
        protocols=("system_one",),
    ),
    # Add more provider profiles here as needed.
}


def is_registered_decision_provider(provider: str) -> bool:
    """Return whether a provider has an explicit structured-decision profile."""
    return provider in _PROVIDER_PROFILES


def registered_decision_provider_names() -> tuple[str, ...]:
    """Return the registered provider names in declaration order."""
    return tuple(_PROVIDER_PROFILES)


def _get_profile(provider: str, protocol: str) -> DecisionProviderProfile:
    profile = _PROVIDER_PROFILES.get(provider)
    if profile is None:
        raise UnsupportedDecisionProviderError(
            f"No decision endpoint is registered for provider {provider!r}"
        )
    if protocol not in profile.protocols:
        raise UnsupportedDecisionProtocolError(
            f"Protocol {protocol!r} is not supported by provider {provider!r}"
        )
    return profile


def _compose_endpoint_url(profile: DecisionProviderProfile) -> str:
    parts = urlsplit(profile.base_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.query
        or parts.fragment
        or not profile.route.strip()
    ):
        raise UnsupportedDecisionProviderError(
            f"Decision endpoint profile for {profile.name!r} is invalid"
        )
    path = f"{parts.path.rstrip('/')}/{profile.route.strip().lstrip('/')}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def resolve_provider_settings(
    *,
    provider: str,
    protocol: str,
    api_key: str | None = None,
    proxy: str | None = None,
) -> DecisionProviderSettings:
    """Resolve settings only from an explicitly registered provider profile."""
    profile = _get_profile(provider, protocol)
    resolved_key = (api_key or "").strip()
    if not resolved_key and profile.api_key_env:
        resolved_key = os.environ.get(profile.api_key_env, "").strip()
    return DecisionProviderSettings(
        name=profile.name,
        protocol=protocol,
        endpoint_url=_compose_endpoint_url(profile),
        api_key=resolved_key or None,
        proxy=(proxy or "").strip() or None,
        requires_api_key=profile.requires_api_key,
    )


def resolve_provider_settings_from_config(
    config: Config,
    *,
    provider: str,
    protocol: str,
) -> DecisionProviderSettings:
    """Resolve profile credentials and proxy from ``providers.<provider>``."""
    _get_profile(provider, protocol)
    from nanobot.config.loader import resolve_env_refs
    from nanobot.config.schema import ProviderConfig

    provider_config = getattr(config.providers, provider, None)
    if provider_config is None:
        provider_config = (config.providers.model_extra or {}).get(provider)
    if not isinstance(provider_config, ProviderConfig):
        raise UnsupportedDecisionProviderError(
            f"Provider settings are not configured for {provider!r}"
        )

    api_key = resolve_env_refs(provider_config.api_key or "").strip() or None
    proxy = resolve_env_refs(provider_config.proxy or "").strip() or None
    return resolve_provider_settings(
        provider=provider,
        protocol=protocol,
        api_key=api_key,
        proxy=proxy,
    )
