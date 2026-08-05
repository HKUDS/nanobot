"""Resolve user-facing provider capability switches with legacy compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nanobot.config.schema import ProviderConfig
    from nanobot.providers.registry import ProviderSpec

FAST_MODE = "fast_mode"
NATIVE_SEARCH = "native_search"

_NATIVE_SEARCH_TOOL_TYPES = frozenset({"web_search", "web_search_preview"})


def resolve_provider_capability(
    spec: ProviderSpec | None,
    provider_config: ProviderConfig | None,
    name: str,
) -> bool | None:
    """Return the effective supported capability value, or ``None`` if unsupported."""
    if spec is None:
        return None
    capability = next(
        (candidate for candidate in spec.capabilities if candidate.name == name),
        None,
    )
    if capability is None:
        return None

    configured = provider_config.capabilities if provider_config is not None else {}
    if name in configured:
        return configured[name]

    extra_body = provider_config.extra_body if provider_config is not None else None
    if name == FAST_MODE and _legacy_fast_mode_enabled(extra_body):
        return True
    if name == NATIVE_SEARCH and _legacy_native_search_enabled(extra_body):
        return True
    return capability.default_enabled


def is_native_search_tool(tool: object) -> bool:
    """Return whether a Responses tool entry enables provider-hosted web search."""
    if not isinstance(tool, dict):
        return False
    tool_type = cast(dict[object, object], tool).get("type")
    return isinstance(tool_type, str) and tool_type in _NATIVE_SEARCH_TOOL_TYPES


def _legacy_fast_mode_enabled(extra_body: dict[str, Any] | None) -> bool:
    if not extra_body:
        return False
    service_tier = extra_body.get("service_tier")
    return isinstance(service_tier, str) and service_tier.lower() == "priority"


def _legacy_native_search_enabled(extra_body: dict[str, Any] | None) -> bool:
    if not extra_body:
        return False
    tools = extra_body.get("tools")
    return isinstance(tools, list) and any(
        is_native_search_tool(tool) for tool in cast(list[object], tools)
    )
