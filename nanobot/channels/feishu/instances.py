"""Feishu-owned helpers for its persisted multi-instance configuration."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.channels.contracts import ChannelInstanceSpec, ChannelManagementSpec
from nanobot.channels.feishu.config import feishu_default_config
from nanobot.config.loader import merge_missing_defaults

DEFAULT_INSTANCE_ID = "default"
_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_instance_id(value: str) -> str:
    """Return a normalized instance id or raise ValueError."""
    instance_id = value.strip()
    if not instance_id or not _INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("instance id must match [A-Za-z0-9_-]+")
    return instance_id


def runtime_channel_name(base_name: str, instance_id: str) -> str:
    """Return the channel key used for routing messages at runtime."""
    return base_name if instance_id == DEFAULT_INSTANCE_ID else f"{base_name}.{instance_id}"


def managed_feishu_instance_specs(
    section: Any,
    *,
    enabled_only: bool = True,
) -> list[ChannelInstanceSpec]:
    return feishu_instance_specs(
        section,
        feishu_default_config(),
        enabled_only=enabled_only,
    )


def update_managed_feishu_instance(
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = DEFAULT_INSTANCE_ID,
) -> dict[str, Any]:
    existing = section if isinstance(section, dict) else {}
    return upsert_feishu_instance(
        existing,
        feishu_default_config(),
        instance_id,
        values,
    )


def _base_feishu_instance_config(defaults: dict[str, Any]) -> dict[str, Any]:
    config = dict(defaults)
    config["instanceId"] = DEFAULT_INSTANCE_ID
    config["name"] = "nanobot"
    return config


def _normalize_feishu_instance(
    raw: dict[str, Any],
    defaults: dict[str, Any],
    *,
    inherited: dict[str, Any] | None = None,
    fallback_id: str = DEFAULT_INSTANCE_ID,
) -> dict[str, Any]:
    config = merge_missing_defaults(inherited or {}, defaults)
    config = merge_missing_defaults(raw, config)

    raw_id = raw.get("id") or raw.get("instanceId") or raw.get("instance_id") or fallback_id
    instance_id = validate_instance_id(str(raw_id))
    config["id"] = instance_id
    config["instanceId"] = instance_id
    config.setdefault("name", "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}")
    return config


def feishu_app_identity_key(app_id: Any, domain: Any = "feishu") -> str:
    """Return the stable identity shared by persisted and runtime instances."""
    app_id = str(app_id or "").strip()
    if not app_id:
        return ""
    normalized_domain = "lark" if str(domain or "feishu").strip().lower() == "lark" else "feishu"
    return f"{normalized_domain}:{app_id}"


def _feishu_instance_inputs(
    section: Any,
    defaults: dict[str, Any],
) -> tuple[list[Any], dict[str, Any] | None]:
    if hasattr(section, "model_dump"):
        section = section.model_dump(mode="json", by_alias=True)
    if not isinstance(section, dict):
        section = {}

    instances = section.get("instances")
    if isinstance(instances, list):
        inherited = {key: value for key, value in section.items() if key != "instances"}
        return list(instances), inherited
    return ([section] if section else [_base_feishu_instance_config(defaults)]), None


def feishu_instance_specs(
    section: Any,
    defaults: dict[str, Any],
    *,
    enabled_only: bool = False,
) -> list[ChannelInstanceSpec]:
    """Expand legacy or canonical Feishu config into runtime instance specs."""
    raw_specs, inherited = _feishu_instance_inputs(section, defaults)

    specs: list[ChannelInstanceSpec] = []
    instance_ids: set[str] = set()
    identity_owners: dict[str, str] = {}
    for index, raw in enumerate(raw_specs):
        if not isinstance(raw, dict):
            logger.warning("Skipping invalid Feishu instance at index {}: expected an object", index)
            continue
        fallback_id = DEFAULT_INSTANCE_ID if index == 0 else f"assistant-{index + 1}"
        try:
            config = _normalize_feishu_instance(
                raw,
                defaults,
                inherited=inherited,
                fallback_id=fallback_id,
            )
        except ValueError as exc:
            logger.warning("Skipping invalid Feishu instance config: {}", exc)
            continue

        instance_id = str(config["instanceId"])
        if instance_id in instance_ids:
            logger.warning("Skipping duplicate Feishu instance id '{}'", instance_id)
            continue

        instance_ids.add(instance_id)
        enabled = bool(config.get("enabled", defaults.get("enabled", False)))
        if enabled_only and not enabled:
            continue

        identity = feishu_app_identity_key(
            config.get("appId") or config.get("app_id"),
            config.get("domain"),
        )
        if enabled_only and identity:
            if identity in identity_owners:
                logger.warning(
                    "Skipping Feishu instance '{}' because it uses the same app as instance '{}'",
                    instance_id,
                    identity_owners[identity],
                )
                continue
            identity_owners[identity] = instance_id

        specs.append(
            ChannelInstanceSpec(
                instance_id=instance_id,
                config=config,
            )
        )

    return specs


def canonical_feishu_section(section: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical section, rejecting input that cannot be preserved safely."""
    raw_specs, inherited = _feishu_instance_inputs(section, defaults)
    instances: list[dict[str, Any]] = []
    instance_ids: set[str] = set()

    for index, raw in enumerate(raw_specs):
        if not isinstance(raw, dict):
            raise ValueError(f"Feishu instance at index {index} must be an object")
        fallback_id = DEFAULT_INSTANCE_ID if index == 0 else f"assistant-{index + 1}"
        try:
            config = _normalize_feishu_instance(
                raw,
                defaults,
                inherited=inherited,
                fallback_id=fallback_id,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid Feishu instance at index {index}: {exc}") from exc

        instance_id = str(config["instanceId"])
        if instance_id in instance_ids:
            raise ValueError(f"duplicate Feishu instance id '{instance_id}'")
        instance_ids.add(instance_id)
        instances.append(config)

    return {"instances": instances}


def upsert_feishu_instance(
    section: Any,
    defaults: dict[str, Any],
    instance_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Return canonical Feishu section with one instance created or updated."""
    instance_id = validate_instance_id(instance_id)
    canonical = canonical_feishu_section(section, defaults)
    instances = canonical.setdefault("instances", [])

    for instance in instances:
        if instance.get("id") == instance_id or instance.get("instanceId") == instance_id:
            instance.update(values)
            instance["id"] = instance_id
            instance["instanceId"] = instance_id
            instance.setdefault("name", "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}")
            return canonical

    config = _normalize_feishu_instance(
        {**values, "id": instance_id},
        defaults,
        fallback_id=instance_id,
    )
    instances.append(config)
    return canonical


def update_feishu_instance_preserving_shape(
    section: Any,
    defaults: dict[str, Any],
    instance_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Update background metadata without migrating a legacy flat section."""
    instance_id = validate_instance_id(instance_id)
    if hasattr(section, "model_dump"):
        section = section.model_dump(mode="json", by_alias=True)

    if (
        instance_id == DEFAULT_INSTANCE_ID
        and isinstance(section, dict)
        and not isinstance(section.get("instances"), list)
    ):
        return {**section, **values}

    return upsert_feishu_instance(section, defaults, instance_id, values)


FEISHU_MANAGEMENT = ChannelManagementSpec(
    multi_instance=True,
    default_config=feishu_default_config,
    instance_specs=managed_feishu_instance_specs,
    update_instance_config=update_managed_feishu_instance,
    runtime_name=runtime_channel_name,
)


__all__ = [
    "DEFAULT_INSTANCE_ID",
    "FEISHU_MANAGEMENT",
    "canonical_feishu_section",
    "feishu_app_identity_key",
    "feishu_instance_specs",
    "runtime_channel_name",
    "update_feishu_instance_preserving_shape",
    "upsert_feishu_instance",
    "validate_instance_id",
]
