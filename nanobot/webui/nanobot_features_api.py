"""Nanobot optional feature helpers for WebUI Settings."""
from __future__ import annotations

from typing import Any

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


def nanobot_features_action(
    action: str,
    query: QueryParams,
    *,
    allow_install: bool = True,
) -> dict[str, Any]:
    name = (query_first(query, "name") or "").strip()
    if not name:
        raise OptionalFeatureError("missing feature name")
    if action == "enable":
        return enable_optional_feature(name, allow_install=allow_install)
    if action == "disable":
        if name == "websocket":
            raise OptionalFeatureError(
                "The WebUI websocket channel cannot be disabled from WebUI. "
                "Use `nanobot plugins disable websocket` from a terminal if you need to disable it.",
                status=400,
            )
        return disable_optional_feature(name)
    raise OptionalFeatureError(f"unknown feature action '{action}'", status=404)
