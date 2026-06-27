"""Nanobot optional feature helpers for WebUI Settings."""
from __future__ import annotations

from typing import Any

from nanobot.optional_features import (
    OptionalFeatureError,
    enable_optional_feature,
    optional_features_payload,
)

QueryParams = dict[str, list[str]]


def _query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def nanobot_features_payload() -> dict[str, Any]:
    return optional_features_payload()


def nanobot_features_action(action: str, query: QueryParams) -> dict[str, Any]:
    name = (_query_first(query, "name") or "").strip()
    if not name:
        raise OptionalFeatureError("missing feature name")
    if action == "enable":
        return enable_optional_feature(name)
    raise OptionalFeatureError(f"unknown feature action '{action}'", status=404)
