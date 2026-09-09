"""Transport-neutral, complete configuration editor contract.

The contract intentionally exposes a redacted typed draft plus the Pydantic
JSON schema. UI clients can present a small guided surface and still offer an
advanced editor without duplicating nanobot's configuration model.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from nanobot.channels.registry import discover_plugins
from nanobot.config.errors import validation_issues
from nanobot.config.loader import config_to_persisted_data, load_config, save_config
from nanobot.config.schema import Config

CONFIG_EDITOR_VERSION = 1

_SECRET_KEY_NAMES = frozenset(
    {
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
    }
)
_SECRET_KEY_SUFFIXES = (
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
_DEPRECATED_PATHS = (
    "/channels/extractDocumentText",
    "/channels/transcriptionProvider",
    "/channels/transcriptionLanguage",
)
_PRESENTATION = {
    "primary_paths": [
        "/agents/defaults/workspace",
        "/agents/defaults/modelPreset",
        "/agents/defaults/model",
        "/agents/defaults/provider",
    ],
    "provider_primary_fields": ["apiKey", "apiBase"],
    "sections": [
        {
            "id": "models",
            "label": "Models and providers",
            "description": "Choose the models nanobot uses and connect their providers.",
            "prefixes": [
                "/agents/defaults/modelPreset",
                "/agents/defaults/model",
                "/agents/defaults/provider",
                "/agents/defaults/maxTokens",
                "/agents/defaults/contextWindowTokens",
                "/agents/defaults/contextBlockLimit",
                "/agents/defaults/temperature",
                "/agents/defaults/fallbackModels",
                "/agents/defaults/reasoningEffort",
                "/modelPresets",
                "/providers",
            ],
        },
        {
            "id": "agent",
            "label": "Agent",
            "description": "Workspace, identity, sessions, memory, and agent behavior.",
            "prefixes": ["/agents"],
        },
        {
            "id": "channels",
            "label": "Channels",
            "description": "Chat integrations and behavior shared across channels.",
            "prefixes": ["/channels"],
        },
        {
            "id": "tools",
            "label": "Tools",
            "description": "Filesystem, shell, web, image generation, MCP, and safety controls.",
            "prefixes": ["/tools"],
        },
        {
            "id": "transcription",
            "label": "Transcription",
            "description": "Audio transcription defaults shared by chat channels.",
            "prefixes": ["/transcription"],
        },
        {
            "id": "api",
            "label": "API server",
            "description": "OpenAI-compatible API endpoint and authentication.",
            "prefixes": ["/api"],
        },
        {
            "id": "gateway",
            "label": "Gateway",
            "description": "Gateway network, restart, and heartbeat behavior.",
            "prefixes": ["/gateway"],
        },
    ],
    "deprecated_paths": list(_DEPRECATED_PATHS),
}


class ConfigEditorError(ValueError):
    """A safe user-facing configuration editor failure."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.issues = issues or []


def config_editor_snapshot(*, config_path: Path) -> dict[str, Any]:
    """Return a complete redacted draft and its presentation contract."""
    config = load_config(config_path)
    persisted = config_to_persisted_data(config)
    redacted, secrets = _redacted_config(persisted)
    return {
        "version": CONFIG_EDITOR_VERSION,
        "revision": _revision(persisted),
        "config": redacted,
        "schema": _config_editor_schema(),
        "secrets": secrets,
        "presentation": deepcopy(_PRESENTATION),
    }


def _config_editor_schema() -> dict[str, Any]:
    """Augment the typed config schema with dependency-free channel manifests."""
    schema = Config.model_json_schema(mode="validation", by_alias=True)
    raw_properties = schema.get("properties")
    raw_definitions = schema.get("$defs")
    if not isinstance(raw_properties, dict) or not isinstance(raw_definitions, dict):
        return schema
    properties = cast(dict[str, Any], raw_properties)
    definitions = cast(dict[str, Any], raw_definitions)
    channels_ref = properties.get("channels")
    if not isinstance(channels_ref, dict):
        return schema
    typed_channels_ref = cast(dict[str, Any], channels_ref)
    ref = typed_channels_ref.get("$ref")
    if not isinstance(ref, str):
        return schema
    definition_name = ref.rsplit("/", maxsplit=1)[-1]
    channels_schema = definitions.get(definition_name)
    if not isinstance(channels_schema, dict):
        return schema
    typed_channels_schema = cast(dict[str, Any], channels_schema)
    channel_properties = typed_channels_schema.setdefault("properties", {})
    if not isinstance(channel_properties, dict):
        return schema
    typed_channel_properties = cast(dict[str, Any], channel_properties)

    for name, plugin in discover_plugins().items():
        if not plugin.settings_visible:
            continue
        setup = plugin.setup
        plugin_properties: dict[str, Any] = {}
        if "always_enabled" not in plugin.capabilities:
            plugin_properties["enabled"] = {
                "type": "boolean",
                "default": plugin.default_enabled,
                "title": "Enabled",
            }
        if setup is not None:
            for field_name, field in setup.fields.items():
                if not field.writable:
                    continue
                _insert_channel_field_schema(
                    plugin_properties,
                    field_name.split("."),
                    _channel_field_schema(field.kind, field.choices, field.default),
                )
        typed_channel_properties[name] = {
            "type": "object",
            "title": plugin.display_name,
            "description": f"{plugin.display_name} channel configuration.",
            "properties": plugin_properties,
            "additionalProperties": True,
        }
    return schema


def _channel_field_schema(kind: str, choices: frozenset[str], default: Any) -> dict[str, Any]:
    if kind == "bool":
        schema: dict[str, Any] = {"type": "boolean"}
    elif kind == "int":
        schema = {"type": "integer"}
    elif kind == "list":
        schema = {"type": "array", "items": {"type": "string"}}
    else:
        schema = {"type": "string"}
    if kind == "enum":
        schema["enum"] = sorted(choices)
    if default is not None:
        schema["default"] = default
    return schema


def _insert_channel_field_schema(
    properties: dict[str, Any],
    parts: list[str],
    field_schema: dict[str, Any],
) -> None:
    name = parts[0]
    if len(parts) == 1:
        properties[name] = field_schema
        return
    parent_value = properties.setdefault(
        name,
        {"type": "object", "properties": {}, "additionalProperties": True},
    )
    if not isinstance(parent_value, dict):
        return
    parent = cast(dict[str, Any], parent_value)
    nested = parent.setdefault("properties", {})
    if isinstance(nested, dict):
        _insert_channel_field_schema(cast(dict[str, Any], nested), parts[1:], field_schema)


def update_config_editor(
    payload: dict[str, Any],
    *,
    config_path: Path,
) -> dict[str, Any]:
    """Validate and persist one optimistic full-document configuration draft."""
    revision = payload.get("revision")
    submitted = payload.get("config")
    if not isinstance(revision, str) or not revision:
        raise ConfigEditorError("Configuration revision is required.")
    if not isinstance(submitted, dict):
        raise ConfigEditorError("Configuration draft must be an object.")

    current = config_to_persisted_data(load_config(config_path))
    if revision != _revision(current):
        raise ConfigEditorError(
            "Configuration changed on disk. Reload it before saving your changes.",
            status=409,
        )

    draft = deepcopy(cast(dict[str, Any], submitted))
    _restore_redacted_secrets(draft, current)
    try:
        config = Config.model_validate(draft)
    except ValidationError as exc:
        issues = [
            {
                "path": "/" + "/".join(_pointer_escape(str(part)) for part in issue.path),
                "message": issue.message,
            }
            for issue in validation_issues(exc)
        ]
        raise ConfigEditorError(
            f"Found {len(issues)} invalid setting(s).",
            issues=issues,
        ) from exc

    save_config(config, config_path)
    return config_editor_snapshot(config_path=config_path)


def _revision(value: dict[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(_pointer_escape(part) for part in parts)


def _compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _secret_key(value: str) -> bool:
    compact = _compact_key(value)
    return compact in _SECRET_KEY_NAMES or compact.endswith(_SECRET_KEY_SUFFIXES)


def _declared_secret_paths(config: dict[str, Any]) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = {("api", "apiKey"), ("tools", "web", "search", "apiKey")}
    providers = config.get("providers")
    if isinstance(providers, dict):
        provider_map = cast(dict[str, Any], providers)
        paths.update(("providers", name, "apiKey") for name in provider_map)
    for name, plugin in discover_plugins().items():
        setup = plugin.setup
        if setup is None:
            continue
        for field in setup.secrets:
            paths.add(("channels", name, *field.split(".")))
    return paths


def _sensitive_container(parts: tuple[str, ...]) -> bool:
    return len(parts) >= 5 and parts[0] == "tools" and parts[1] == "mcpServers" and (
        parts[3] in {"env", "headers"}
    )


def _redacted_config(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    declared = _declared_secret_paths(config)
    secrets: list[dict[str, Any]] = []

    def redact(value: Any, parts: tuple[str, ...]) -> Any:
        secret = parts in declared or (parts and _secret_key(parts[-1])) or _sensitive_container(parts)
        if secret:
            secrets.append({"path": _pointer(parts), "configured": value not in (None, "")})
            return None
        if isinstance(value, dict):
            return {
                str(key): redact(item, (*parts, str(key)))
                for key, item in cast(dict[str, Any], value).items()
            }
        if isinstance(value, list):
            items = cast(list[Any], value)
            return [redact(item, (*parts, str(index))) for index, item in enumerate(items)]
        return value

    redacted = cast(dict[str, Any], redact(config, ()))
    known = {_pointer(path) for path in declared}
    existing = {item["path"] for item in secrets}
    for path in sorted(known - existing):
        secrets.append({"path": path, "configured": False})
    secrets.sort(key=lambda item: cast(str, item["path"]))
    return redacted, secrets


def _restore_redacted_secrets(submitted: dict[str, Any], current: dict[str, Any]) -> None:
    _redacted, secrets = _redacted_config(current)
    for item in secrets:
        raw_path = cast(str, item["path"])
        parts = tuple(
            part.replace("~1", "/").replace("~0", "~")
            for part in raw_path.removeprefix("/").split("/")
        )
        submitted_parent = _parent_at(submitted, parts)
        current_parent = _parent_at(current, parts)
        if submitted_parent is None or current_parent is None:
            continue
        submitted_container, key = submitted_parent
        current_container, current_key = current_parent
        submitted_value = _item_at(submitted_container, key)
        if submitted_value is not None:
            continue
        current_value = _item_at(current_container, current_key)
        _assign_at(submitted_container, key, deepcopy(current_value))


def _parent_at(
    value: Any,
    parts: tuple[str, ...],
) -> tuple[dict[str, Any] | list[Any], str] | None:
    if not parts:
        return None
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = cast(dict[str, Any], current)[part]
        elif isinstance(current, list) and part.isdigit():
            items = cast(list[Any], current)
            index = int(part)
            if index >= len(items):
                return None
            current = items[index]
        else:
            return None
    if not isinstance(current, (dict, list)):
        return None
    return cast(dict[str, Any] | list[Any], current), parts[-1]


def _item_at(container: dict[str, Any] | list[Any], key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)
    if not key.isdigit() or int(key) >= len(container):
        return None
    return container[int(key)]


def _assign_at(container: dict[str, Any] | list[Any], key: str, value: Any) -> None:
    if isinstance(container, dict):
        container[key] = value
    elif key.isdigit() and int(key) < len(container):
        container[int(key)] = value
