"""Stable compatibility facade for WebUI settings.

The gateway owns serialization and the explicit config path. Business DTOs,
validation, and updates live in the model/provider, capability, and system
domains; this module preserves the established Python and HTTP-facing seams.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from nanobot import __version__
from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
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
    rename_model_preset: Callable[[str, str], int] | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    names_before = set(config.model_presets)
    changed = models.update_model_configuration(
        config,
        query,
        oauth_status=_oauth_provider_status,
    )
    if changed:
        removed = names_before - set(config.model_presets)
        added = set(config.model_presets) - names_before
        rename = (
            (next(iter(removed)), next(iter(added)))
            if len(removed) == len(added) == 1
            else None
        )
        if rename is not None and rename_model_preset is not None:
            rename_model_preset(*rename)
            try:
                _save_settings_config(config, config_path)
            except BaseException:
                rename_model_preset(rename[1], rename[0])
                raise
        else:
            _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def update_model_call_order(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if models.update_model_call_order(
        config,
        query,
        oauth_status=_oauth_provider_status,
    ):
        _save_settings_config(config, config_path)
    return settings_payload(config_path=config_path)


def migrate_model_configurations(
    _query: QueryParams | None = None,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = _load_settings_config(config_path)
    if models.migrate_model_configurations(
        config,
        oauth_status=_oauth_provider_status,
    ):
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
