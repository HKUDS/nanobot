"""Stable compatibility facade for WebUI settings.

The gateway owns serialization and the explicit config path. Business DTOs,
validation, and updates live in the model/provider, capability, and system
domains; this module preserves the established Python and HTTP-facing seams.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from nanobot import __version__
from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.image_generation import get_image_gen_provider
from nanobot.providers.registry import find_by_name
from nanobot.webui import settings_capabilities as capabilities
from nanobot.webui import settings_contracts as contracts
from nanobot.webui import settings_models as models
from nanobot.webui import settings_system as system
from nanobot.webui.settings_contracts import QueryParams, WebUISettingsError
from nanobot.webui.workspaces import write_webui_default_access_mode

if TYPE_CHECKING:
    from nanobot.webui.settings_services import WebUIOAuthFlowRegistry

RuntimeSurface = Literal["browser", "native"]

# Preserve established direct imports of focused helpers.
_docs_version = system.docs_version
_parse_bool = contracts.parse_bool
_query_first = contracts.query_first
_query_first_alias = contracts.query_first_alias
_query_has_alias = contracts.query_has_alias
_model_catalog_kind = models.model_catalog_kind
_oauth_provider_status = models.oauth_provider_status
_provider_requires_api_key = models.provider_requires_api_key
_reasoning_effort_values_for = models.reasoning_effort_values_for


_RUNTIME_CAPABILITIES = {
    "can_restart_engine": False,
    "can_pick_folder": False,
    "can_open_logs": False,
    "can_export_diagnostics": False,
}
_NATIVE_RUNTIME_CAPABILITIES = {
    **_RUNTIME_CAPABILITIES,
    "can_restart_engine": True,
    "can_pick_folder": True,
    "can_open_logs": True,
    "can_export_diagnostics": True,
}
_BROWSER_RESTART_BEHAVIOR_BY_SECTION = {
    "appearance": "none",
    "models": "none",
    "providers": "none",
    "runtime": "engineRestart",
    "browser": "engineRestart",
    "image": "engineRestart",
    "apps": "engineRestart",
    "advanced": "appRestart",
}
_NATIVE_RESTART_BEHAVIOR_BY_SECTION = {
    **_BROWSER_RESTART_BEHAVIOR_BY_SECTION,
    "runtime": "engineRestart",
    "browser": "engineRestart",
    "image": "engineRestart",
    "apps": "engineRestart",
}


def _load_settings_config(config_path: Path | None) -> Config:
    return load_config(config_path) if config_path is not None else load_config()


def _save_settings_config(config: Config, config_path: Path | None) -> None:
    if config_path is None:
        save_config(config)
    else:
        save_config(config, config_path)


def _settings_config_path(config_path: Path | None) -> Path:
    return config_path if config_path is not None else get_config_path()


def _normalize_surface(surface: str | None) -> RuntimeSurface:
    return "native" if surface in {"native", "desktop"} else "browser"


def runtime_capabilities(
    surface: str | None = "browser",
    overrides: dict[str, Any] | None = None,
) -> dict[str, bool]:
    base = (
        _NATIVE_RUNTIME_CAPABILITIES
        if _normalize_surface(surface) == "native"
        else _RUNTIME_CAPABILITIES
    )
    result = dict(base)
    for key, value in (overrides or {}).items():
        if key in result:
            result[key] = bool(value)
    return result


def restart_behavior_by_section(surface: str | None = "browser") -> dict[str, str]:
    return dict(
        _NATIVE_RESTART_BEHAVIOR_BY_SECTION
        if _normalize_surface(surface) == "native"
        else _BROWSER_RESTART_BEHAVIOR_BY_SECTION
    )


def decorate_settings_payload(
    payload: dict[str, Any],
    *,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach runtime-surface metadata without changing the core settings shape."""
    surface_value = _normalize_surface(surface)
    sections = restart_required_sections
    if sections is None:
        raw_sections: object = payload.get("restart_required_sections") or []
        sections = [
            section
            for section in cast(Iterable[object], raw_sections)
            if isinstance(section, str)
        ]
    sections = sorted(dict.fromkeys(sections))
    result = dict(payload)
    result["surface"] = surface_value
    result["runtime_surface"] = surface_value
    result["runtime_capabilities"] = runtime_capabilities(
        surface_value,
        runtime_capability_overrides,
    )
    result["restart_behavior_by_section"] = restart_behavior_by_section(surface_value)
    result["restart_required_sections"] = sections
    if sections:
        result["requires_restart"] = True
    else:
        result["requires_restart"] = bool(result.get("requires_restart", False))
    result["apply_state"] = apply_state or {
        "status": "pending" if result["requires_restart"] else "idle",
        "sections": sections,
    }
    return result


def settings_payload(
    *,
    requires_restart: bool = False,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    payload: dict[str, Any] = {
        **models.model_settings_payload(
            config,
            oauth_status=_oauth_provider_status,
        ),
        **capabilities.capability_settings_payload(
            config,
            oauth_status=_oauth_provider_status,
        ),
        **system.system_settings_payload(
            config,
            config_path=_settings_config_path(config_path),
            version=__version__,
        ),
        "requires_restart": requires_restart,
    }
    return decorate_settings_payload(
        payload,
        surface=surface,
        runtime_capability_overrides=runtime_capability_overrides,
        restart_required_sections=restart_required_sections,
        apply_state=apply_state,
    )


def settings_usage_payload(*, config_path: Path | None = None) -> dict[str, Any]:
    return system.settings_usage_payload(_load_settings_config(config_path))


def update_agent_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    model_changed = models.update_agent_model_settings(
        config,
        query,
        oauth_status=_oauth_provider_status,
    )
    system_changed, restart_required = system.update_agent_system_settings(config, query)
    if model_changed or system_changed:
        _save_settings_config(config, config_path)
    return settings_payload(
        requires_restart=restart_required,
        config_path=config_path,
    )


def create_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    name = models.create_model_configuration(
        config,
        query,
        oauth_status=_oauth_provider_status,
    )
    _save_settings_config(config, config_path)
    payload = settings_payload(config_path=config_path)
    payload["created_model_preset"] = name
    return payload


def update_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if models.update_model_configuration(
        config,
        query,
        oauth_status=_oauth_provider_status,
    ):
        _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def update_model_call_order(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if models.update_model_call_order(config, query):
        _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def migrate_model_configurations(
    _query: QueryParams | None = None,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if models.migrate_model_configurations(config):
        _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def delete_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    models.delete_model_configuration(config, query)
    _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def create_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    provider_key = models.create_provider_settings(config, query)
    _save_settings_config(config, config_path)
    payload = settings_payload(config_path=config_path)
    payload["created_provider"] = provider_key
    return payload


def _normalized_provider_reference(value: str) -> str:
    return value.strip().replace("-", "_").casefold()


def _resolve_settings_provider(
    config: Config,
    provider_name: str,
) -> tuple[Any, str, Any] | None:
    return models.resolve_settings_provider(config, provider_name)


def _provider_configured_for_settings(spec: Any, provider_config: Any) -> bool:
    return models.provider_configured_for_settings(
        spec,
        provider_config,
        models.oauth_provider_status,
    )


def _preset_uses_provider(
    config: Config,
    preset: ModelPresetConfig,
    provider_key: str,
) -> bool:
    provider = _normalized_provider_reference(preset.provider)
    if provider == provider_key:
        return True
    if provider != "auto":
        return False
    resolved_provider = config.get_provider_name(model=preset.model, preset=preset)
    return _normalized_provider_reference(resolved_provider or "") == provider_key


def _provider_dependency_locations(config: Config, provider_key: str) -> list[str]:
    locations: list[str] = []
    defaults = config.agents.defaults
    if _normalized_provider_reference(defaults.provider) == provider_key:
        locations.append("default agent provider")
    elif _preset_uses_provider(config, config.resolve_default_preset(), provider_key):
        locations.append(f'default agent model "{defaults.model}"')

    for name, preset in config.model_presets.items():
        if _preset_uses_provider(config, preset, provider_key):
            provider = _normalized_provider_reference(preset.provider)
            if provider == provider_key:
                locations.append(f'model preset "{name}"')
            else:
                locations.append(f'model preset "{name}" (model "{preset.model}")')

    for fallback in defaults.fallback_models:
        if isinstance(fallback, str):
            preset = config.model_presets.get(fallback)
            if preset is not None and _preset_uses_provider(config, preset, provider_key):
                locations.append(f'fallback preset "{fallback}"')
            continue
        fallback_preset = ModelPresetConfig(model=fallback.model, provider=fallback.provider)
        if _preset_uses_provider(config, fallback_preset, provider_key):
            locations.append(f'inline fallback "{fallback.model}"')
    return locations


def delete_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")

    config = _load_settings_config(config_path)
    resolved_provider = _resolve_settings_provider(config, provider_name)
    if resolved_provider is None or find_by_name(resolved_provider[1]) is not None:
        raise WebUISettingsError("only custom providers can be deleted")
    _spec, provider_key, provider_config = resolved_provider
    dynamic_providers = config.providers.model_extra
    if dynamic_providers is None or provider_key not in dynamic_providers:
        raise WebUISettingsError("only custom providers can be deleted")

    normalized_key = _normalized_provider_reference(provider_key)
    dependencies = _provider_dependency_locations(config, normalized_key)
    if dependencies:
        raise WebUISettingsError(
            f'provider "{provider_config.display_name or provider_key}" is referenced by: '
            + ", ".join(dependencies),
            status=409,
        )

    del dynamic_providers[provider_key]
    _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def reset_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")

    config = _load_settings_config(config_path)
    resolved_provider = _resolve_settings_provider(config, provider_name)
    if resolved_provider is None:
        raise WebUISettingsError("unknown provider")
    spec, provider_key, provider_config = resolved_provider
    if find_by_name(provider_key) is None or provider_key == "custom":
        raise WebUISettingsError("custom providers must be deleted")
    if spec.is_oauth:
        raise WebUISettingsError("OAuth providers must use sign out instead")
    if not _provider_configured_for_settings(spec, provider_config):
        raise WebUISettingsError("provider is not configured")

    dependencies = _provider_dependency_locations(
        config,
        _normalized_provider_reference(provider_key),
    )
    if dependencies:
        raise WebUISettingsError(
            f'provider "{spec.label}" is referenced by: ' + ", ".join(dependencies),
            status=409,
        )

    image_config = config.tools.image_generation
    restart_required = (
        image_config.enabled
        and image_config.provider == provider_key
        and get_image_gen_provider(provider_key) is not None
    )
    setattr(config.providers, provider_key, type(provider_config)())
    _save_settings_config(config, config_path)
    return settings_payload(requires_restart=restart_required, config_path=config_path)


def update_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    changed, restart_required = models.update_provider_settings(config, query)
    if changed:
        _save_settings_config(config, config_path)
    return settings_payload(
        requires_restart=restart_required,
        config_path=config_path,
    )


def provider_models_payload(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.provider_models_payload(
        _load_settings_config(config_path),
        query,
        http_get=httpx.get,
    )


def login_oauth_provider(
    query: QueryParams,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.login_oauth_provider(
        _load_settings_config(config_path),
        query,
        oauth_flows=oauth_flows,
        config_path=config_path,
        settings_payload=settings_payload,
    )


def complete_oauth_provider(
    query: QueryParams,
    authorization_response: str | None = None,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.complete_oauth_provider(
        query,
        authorization_response,
        oauth_flows=oauth_flows,
        config_path=config_path,
        settings_payload=settings_payload,
    )


def logout_oauth_provider(
    query: QueryParams,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.logout_oauth_provider(
        query,
        oauth_flows=oauth_flows,
        config_path=config_path,
        settings_payload=settings_payload,
    )


def update_network_safety_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    changed, default_access_mode = capabilities.update_network_safety_settings(
        config,
        query,
    )
    if changed:
        _save_settings_config(config, config_path)
    if default_access_mode is not None:
        try:
            write_webui_default_access_mode(default_access_mode)
        except ValueError as exc:
            raise WebUISettingsError(str(exc)) from exc
    return settings_payload(requires_restart=changed, config_path=config_path)


def update_web_search_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    changed, restart_required = capabilities.update_web_search_settings(config, query)
    if changed:
        _save_settings_config(config, config_path)
    return settings_payload(
        requires_restart=restart_required,
        config_path=config_path,
    )


def update_api_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    capabilities.update_api_settings(config, query)
    _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def update_image_generation_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    changed = capabilities.update_image_generation_settings(
        config,
        query,
        oauth_status=_oauth_provider_status,
    )
    if changed:
        _save_settings_config(config, config_path)
    return settings_payload(requires_restart=changed, config_path=config_path)


def update_transcription_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if capabilities.update_transcription_settings(config, query):
        _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)
