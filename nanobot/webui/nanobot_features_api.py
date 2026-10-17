"""Nanobot optional feature helpers for WebUI Settings."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.channels.registry import load_channel_plugin
from nanobot.config.loader import get_config_path
from nanobot.optional_features import (
    OptionalFeatureError,
    install_optional_feature_support,
    optional_features_payload,
    prepare_optional_feature,
    update_optional_feature,
)
from nanobot.webui.http_utils import query_first
from nanobot.webui.settings_services import WebUISettingsConfig

QueryParams = dict[str, list[str]]


def nanobot_features_payload(*, config_path: Path | None = None) -> dict[str, Any]:
    if config_path is None:
        return optional_features_payload()

    from nanobot.config.loader import load_config

    return optional_features_payload(config=load_config(config_path))


def nanobot_feature_instance_target(query: QueryParams) -> str | None:
    """Preserve the difference between a global action and an explicit instance."""
    instance_id = query_first(query, "instance_id")
    if instance_id is None:
        return None
    return instance_id.strip() or None


def nanobot_features_action(
    action: str,
    query: QueryParams,
    *,
    allow_install: bool = True,
    config_path: Path | None = None,
) -> dict[str, Any]:
    return update_nanobot_feature(
        WebUISettingsConfig(config_path or get_config_path()), action, query, allow_install=allow_install,
    )


def update_nanobot_feature(
    store: WebUISettingsConfig,
    action: str,
    query: QueryParams,
    *,
    allow_install: bool = True,
) -> dict[str, Any]:
    name = (query_first(query, "name") or "").strip()
    instance_id = nanobot_feature_instance_target(query)
    raw_install_only = query_first(query, "install_only")
    install_only = False
    if raw_install_only is not None:
        normalized = raw_install_only.strip().lower()
        if normalized not in {"1", "0", "true", "false", "yes", "no"}:
            raise OptionalFeatureError("install_only must be boolean")
        install_only = normalized in {"1", "true", "yes"}
        if action != "enable":
            raise OptionalFeatureError("install_only is only supported for enable actions")
    if not name:
        raise OptionalFeatureError("missing feature name")
    if action == "enable":
        if install_only:
            return install_optional_feature_support(
                name,
                config_path=store.path,
                allow_install=allow_install,
            )
        prepared = prepare_optional_feature(name, enabled=True, allow_install=allow_install, instance_id=instance_id)
        return store.update(lambda config: update_optional_feature(config, prepared, enabled=True))
    if action == "disable":
        try:
            plugin = load_channel_plugin(name)
        except ImportError:
            plugin = None
        if plugin is not None and "always_enabled" in plugin.capabilities:
            raise OptionalFeatureError(
                f"The {plugin.display_name} channel cannot be disabled from WebUI. "
                f"Use `nanobot plugins disable {name}` from a terminal if you need to disable it.",
                status=400,
            )
        prepared = prepare_optional_feature(name, enabled=False, instance_id=instance_id)
        return store.update(lambda config: update_optional_feature(config, prepared, enabled=False))
    raise OptionalFeatureError(f"unknown feature action '{action}'", status=404)
