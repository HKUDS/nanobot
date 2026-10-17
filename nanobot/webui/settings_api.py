"""Stable compatibility facade for WebUI settings.

The gateway owns serialization and the explicit config path. Business DTOs,
validation, and updates live in the model/provider, capability, and system
domains; this module preserves the established Python and HTTP-facing seams.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from nanobot import __version__
from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui import settings_capabilities as capabilities
from nanobot.webui import settings_contracts as contracts
from nanobot.webui import settings_models as models
from nanobot.webui import settings_runtime as runtime
from nanobot.webui import settings_system as system
from nanobot.webui.settings_contracts import QueryParams, WebUISettingsError
from nanobot.webui.settings_services import WebUISettingsConfig
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
    "can_open_logs": False,
    "can_export_diagnostics": False,
}
_NATIVE_RUNTIME_CAPABILITIES = {
    **_RUNTIME_CAPABILITIES,
    "can_restart_engine": True,
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


def _settings_payload_from_config(
    config: Config,
    config_path: Path,
    *,
    requires_restart: bool = False,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        **models.model_settings_payload(config, oauth_status=_oauth_provider_status),
        **capabilities.capability_settings_payload(config, oauth_status=_oauth_provider_status),
        **system.system_settings_payload(config, config_path=config_path, version=__version__),
        "requires_restart": requires_restart,
    }
    return decorate_settings_payload(
        payload,
        surface=surface,
        runtime_capability_overrides=runtime_capability_overrides,
        restart_required_sections=restart_required_sections,
        apply_state=apply_state,
    )


class _FacadeSettingsConfig(WebUISettingsConfig):
    def __init__(self, config_path: Path | None) -> None:
        self._facade_path = config_path
        super().__init__(_settings_config_path(config_path))

    def _read(self) -> Config:
        return _load_settings_config(self._facade_path)

    def _write(self, config: Config) -> None:
        _save_settings_config(config, self._facade_path)


@dataclass(frozen=True)
class _ModelRename:
    config: Config
    names: tuple[str, str] | None


class SettingsOperations:
    """Settings operations bound to one raw configuration store."""

    def __init__(self, config: WebUISettingsConfig) -> None:
        self.config = config

    def features_payload(self) -> dict[str, Any]:
        from nanobot.optional_features import optional_features_payload

        return optional_features_payload(config=self.config.load())

    def feature_action(
        self, action: str, query: QueryParams, *, allow_install: bool = True,
    ) -> dict[str, Any]:
        from nanobot.webui.nanobot_features_api import update_nanobot_feature

        return update_nanobot_feature(self.config, action, query, allow_install=allow_install)

    def payload(
        self,
        *,
        requires_restart: bool = False,
        surface: str | None = "browser",
        runtime_capability_overrides: dict[str, Any] | None = None,
        restart_required_sections: list[str] | None = None,
        apply_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _settings_payload_from_config(
            self.config.load(), self.config.path,
            requires_restart=requires_restart,
            surface=surface,
            runtime_capability_overrides=runtime_capability_overrides,
            restart_required_sections=restart_required_sections,
            apply_state=apply_state,
        )

    def usage_payload(self) -> dict[str, Any]:
        return system.settings_usage_payload(self.config.load())

    def update_agent(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool]:
            models.update_agent_model_settings(config, query, oauth_status=_oauth_provider_status)
            _, restart = system.update_agent_system_settings(config, query)
            return config, restart

        config, restart = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path, requires_restart=restart)

    def create_model(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, str]:
            name = models.create_model_configuration(config, query, oauth_status=_oauth_provider_status)
            return config, name

        config, name = self.config.update(mutation)
        payload = _settings_payload_from_config(config, self.config.path)
        payload["created_model_preset"] = name
        return payload

    def update_model(
        self,
        query: QueryParams,
        *,
        rename_model_preset: Callable[[str, str], int] | None = None,
    ) -> dict[str, Any]:
        def mutation(config: Config) -> _ModelRename:
            names_before = set(config.model_presets)
            changed = models.update_model_configuration(config, query, oauth_status=_oauth_provider_status)
            removed = names_before - set(config.model_presets)
            added = set(config.model_presets) - names_before
            rename = (
                (next(iter(removed)), next(iter(added)))
                if changed and len(removed) == len(added) == 1 else None
            )
            if rename is not None and rename_model_preset is not None:
                rename_model_preset(*rename)
            return _ModelRename(config, rename)

        def rollback(result: _ModelRename) -> None:
            if result.names is not None and rename_model_preset is not None:
                rename_model_preset(result.names[1], result.names[0])

        result = self.config.update(mutation, on_save_error=rollback)
        return _settings_payload_from_config(result.config, self.config.path)

    def update_call_order(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> Config:
            models.update_model_call_order(config, query, oauth_status=_oauth_provider_status)
            return config

        config = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path)

    def migrate_models(self, _query: QueryParams | None = None) -> dict[str, Any]:
        def mutation(config: Config) -> Config:
            models.migrate_model_configurations(config, oauth_status=_oauth_provider_status)
            return config

        config = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path)

    def delete_model(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> Config:
            models.delete_model_configuration(config, query)
            return config

        config = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path)

    def create_provider(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, str]:
            return config, models.create_provider_settings(config, query)

        config, name = self.config.update(mutation)
        payload = _settings_payload_from_config(config, self.config.path)
        payload["created_provider"] = name
        return payload

    def update_provider(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool]:
            _, restart = models.update_provider_settings(config, query)
            return config, restart

        config, restart = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path, requires_restart=restart)

    def model_api(self, query: QueryParams) -> dict[str, Any]:
        return models.model_api_resolution_payload(self.config.load(), query)

    def provider_models(self, query: QueryParams) -> dict[str, Any]:
        return models.provider_models_payload(self.config.load(), query, http_get=httpx.get)

    def oauth_login(
        self, query: QueryParams, *, oauth_flows: WebUIOAuthFlowRegistry,
    ) -> dict[str, Any]:
        return models.login_oauth_provider(
            self.config.load(), query, oauth_flows=oauth_flows, config_path=self.config.path,
        )

    def oauth_complete(
        self, query: QueryParams, authorization_response: str | None = None,
        *, oauth_flows: WebUIOAuthFlowRegistry,
    ) -> dict[str, Any]:
        return models.complete_oauth_provider(
            query, authorization_response, oauth_flows=oauth_flows, read_settings=self.payload,
        )

    def oauth_logout(
        self, query: QueryParams, *, oauth_flows: WebUIOAuthFlowRegistry,
    ) -> dict[str, Any]:
        return models.logout_oauth_provider(query, oauth_flows=oauth_flows, read_settings=self.payload)

    def update_network(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool, str | None]:
            changed, mode = capabilities.update_network_safety_settings(config, query)
            return config, changed, mode

        config, changed, mode = self.config.update(mutation)
        if mode is not None:
            try:
                write_webui_default_access_mode(mode)
            except ValueError as exc:
                raise WebUISettingsError(str(exc)) from exc
        return _settings_payload_from_config(config, self.config.path, requires_restart=changed)

    def update_web_search(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool]:
            _, restart = capabilities.update_web_search_settings(config, query)
            return config, restart

        config, restart = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path, requires_restart=restart)

    def update_api(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> Config:
            capabilities.update_api_settings(config, query)
            return config

        config = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path)

    def update_image(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool]:
            changed = capabilities.update_image_generation_settings(config, query, oauth_status=_oauth_provider_status)
            return config, changed

        config, changed = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path, requires_restart=changed)

    def update_transcription(self, query: QueryParams) -> dict[str, Any]:
        def mutation(config: Config) -> Config:
            capabilities.update_transcription_settings(config, query)
            return config

        config = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path)

    def update_runtime_config(
        self, values: dict[str, Any], *, local_browser: bool = False,
    ) -> dict[str, Any]:
        def mutation(config: Config) -> tuple[Config, bool]:
            changed = runtime.update_runtime_config(config, values, local_browser=local_browser)
            return config, changed

        config, changed = self.config.update(mutation)
        return _settings_payload_from_config(config, self.config.path, requires_restart=changed)


def settings_payload(
    *,
    requires_restart: bool = False,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).payload(
        requires_restart=requires_restart,
        surface=surface,
        runtime_capability_overrides=runtime_capability_overrides,
        restart_required_sections=restart_required_sections,
        apply_state=apply_state,
    )


def settings_usage_payload(*, config_path: Path | None = None) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).usage_payload()


def update_agent_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_agent(query)


def create_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).create_model(query)


def update_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
    rename_model_preset: Callable[[str, str], int] | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_model(
        query, rename_model_preset=rename_model_preset,
    )


def update_model_call_order(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_call_order(query)


def migrate_model_configurations(
    _query: QueryParams | None = None,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).migrate_models(_query)


def delete_model_configuration(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).delete_model(query)


def create_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).create_provider(query)


def update_provider_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_provider(query)


def model_api_resolution_payload(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).model_api(query)


def provider_models_payload(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).provider_models(query)


def login_oauth_provider(
    query: QueryParams,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).oauth_login(query, oauth_flows=oauth_flows)


def complete_oauth_provider(
    query: QueryParams,
    authorization_response: str | None = None,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.complete_oauth_provider(
        query, authorization_response, oauth_flows=oauth_flows,
        read_settings=lambda: settings_payload(config_path=config_path),
    )


def logout_oauth_provider(
    query: QueryParams,
    *,
    oauth_flows: WebUIOAuthFlowRegistry,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return models.logout_oauth_provider(
        query, oauth_flows=oauth_flows,
        read_settings=lambda: settings_payload(config_path=config_path),
    )


def update_network_safety_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_network(query)


def update_web_search_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_web_search(query)


def update_api_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_api(query)


def update_image_generation_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_image(query)


def update_transcription_settings(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_transcription(query)


def update_runtime_config_settings(
    values: dict[str, Any], *, local_browser: bool = False, config_path: Path | None = None,
) -> dict[str, Any]:
    return SettingsOperations(_FacadeSettingsConfig(config_path)).update_runtime_config(
        values, local_browser=local_browser,
    )
