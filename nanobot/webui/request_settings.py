"""Shared validation and secret handling for request settings editors."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from nanobot.config.schema import ProviderConfig
from nanobot.webui.settings_contracts import QueryParams, WebUISettingsError, query_first_alias

_REDACTED_PROVIDER_SECRET = "••••••••"
_PROVIDER_STRUCTURED_FIELDS = ("extra_headers", "extra_body", "extra_query")
_PROVIDER_SECRET_KEYS = frozenset({
    "auth",
    "authentication",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "hmac",
    "key",
    "passphrase",
    "passwd",
    "proxyauthorization",
    "setcookie",
    "sig",
    "signature",
})
_PROVIDER_SECRET_KEY_SUFFIXES = (
    "accesskey",
    "apikey",
    "encryptionkey",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "signingkey",
    "subscriptionkey",
    "token",
)


def parse_request_object(
    query: QueryParams,
    snake: str,
    camel: str,
) -> dict[str, Any] | None:
    raw = (query_first_alias(query, snake, camel) or "").strip()
    if not raw:
        return None
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebUISettingsError(f"{snake} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise WebUISettingsError(f"{snake} must be a JSON object")
    return cast(dict[str, Any], value) or None


def _provider_setting_key_is_secret(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return compact in _PROVIDER_SECRET_KEYS or compact.endswith(_PROVIDER_SECRET_KEY_SUFFIXES)


def redact_request_secrets(value: Any, *, secret: bool = False) -> Any:
    if secret and value not in (None, ""):
        return _REDACTED_PROVIDER_SECRET
    if isinstance(value, dict):
        value_mapping = cast(dict[str, Any], value)
        return {
            key: redact_request_secrets(
                item,
                secret=_provider_setting_key_is_secret(key),
            )
            for key, item in value_mapping.items()
        }
    if isinstance(value, list):
        return [redact_request_secrets(item) for item in cast(list[Any], value)]
    return value


def restore_request_secrets(
    submitted: Any,
    current: Any,
    *,
    secret: bool = False,
) -> Any:
    if secret and submitted == _REDACTED_PROVIDER_SECRET:
        return current
    if isinstance(submitted, dict):
        submitted_mapping = cast(dict[str, Any], submitted)
        current_mapping = cast(dict[str, Any], current) if isinstance(current, dict) else {}
        return {
            key: restore_request_secrets(
                item,
                current_mapping.get(key),
                secret=_provider_setting_key_is_secret(key),
            )
            for key, item in submitted_mapping.items()
        }
    if isinstance(submitted, list):
        submitted_items = cast(list[Any], submitted)
        current_items = cast(list[Any], current) if isinstance(current, list) else []
        return [
            restore_request_secrets(
                item,
                current_items[index] if index < len(current_items) else None,
            )
            for index, item in enumerate(submitted_items)
        ]
    return submitted



def validate_request_config(
    provider_config: ProviderConfig | None,
    updates: dict[str, Any],
) -> ProviderConfig:
    config_type = type(provider_config) if provider_config is not None else ProviderConfig
    values = provider_config.model_dump(mode="python") if provider_config is not None else {}
    if provider_config is not None:
        for field in _PROVIDER_STRUCTURED_FIELDS:
            if field in updates:
                updates[field] = restore_request_secrets(
                    updates[field],
                    getattr(provider_config, field),
                )
    values.update(updates)
    try:
        return config_type.model_validate(values)
    except ValueError as exc:
        errors_callback = getattr(exc, "errors", None)
        errors: list[dict[str, Any]] = (
            cast(Any, errors_callback)() if callable(errors_callback) else []
        )
        if errors:
            error = errors[0]
            field = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "invalid value"))
            raise WebUISettingsError(f"{field}: {message}" if field else message) from exc
        raise WebUISettingsError(str(exc)) from exc
