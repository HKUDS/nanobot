"""Nanobot optional feature helpers for WebUI Settings."""
from __future__ import annotations

from typing import Any

from nanobot.channels.registry import load_channel_plugin
from nanobot.optional_features import (
    OptionalFeatureError,
    disable_optional_feature,
    enable_optional_feature,
    optional_features_payload,
)
from nanobot.webui.http_utils import query_first

QueryParams = dict[str, list[str]]


def nanobot_features_payload() -> dict[str, Any]:
    return optional_features_payload()


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
) -> dict[str, Any]:
    name = (query_first(query, "name") or "").strip()
    instance_id = nanobot_feature_instance_target(query)
    if not name:
        raise OptionalFeatureError("missing feature name")
    if action == "enable":
        return enable_optional_feature(name, allow_install=allow_install, instance_id=instance_id)
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
        return disable_optional_feature(name, instance_id=instance_id)
    raise OptionalFeatureError(f"unknown feature action '{action}'", status=404)
