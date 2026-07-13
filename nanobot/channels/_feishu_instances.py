"""Helpers for channel instance configuration.

The first consumer is Feishu/Lark.  Keep the helpers small and data-oriented so
ChannelManager can support Feishu assistant instances without turning every
channel into a multi-instance abstraction.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.channels.base import ChannelInstanceSpec
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


def feishu_instance_specs(
    section: Any,
    defaults: dict[str, Any],
    *,
    enabled_only: bool = False,
) -> list[ChannelInstanceSpec]:
    """Expand legacy or canonical Feishu config into runtime instance specs."""
    if hasattr(section, "model_dump"):
        section = section.model_dump(mode="json", by_alias=True)
    if not isinstance(section, dict):
        section = {}

    instances = section.get("instances")
    raw_specs: list[dict[str, Any]]
    inherited: dict[str, Any] | None = None
    if isinstance(instances, list):
        inherited = {key: value for key, value in section.items() if key != "instances"}
        raw_specs = [item for item in instances if isinstance(item, dict)]
    else:
        raw_specs = [section] if section else [_base_feishu_instance_config(defaults)]

    specs: list[ChannelInstanceSpec] = []
    for index, raw in enumerate(raw_specs):
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

        enabled = bool(config.get("enabled", defaults.get("enabled", False)))
        if enabled_only and not enabled:
            continue

        instance_id = str(config["instanceId"])
        specs.append(
            ChannelInstanceSpec(
                base_name="feishu",
                instance_id=instance_id,
                runtime_name=runtime_channel_name("feishu", instance_id),
                config=config,
            )
        )

    return specs


def canonical_feishu_section(section: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Return Feishu config in the canonical ``instances`` shape."""
    specs = feishu_instance_specs(section, defaults)
    return {"instances": [dict(spec.config) for spec in specs]}


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


def set_feishu_instance_enabled(
    section: Any,
    defaults: dict[str, Any],
    instance_id: str,
    enabled: bool,
) -> dict[str, Any]:
    """Return canonical Feishu section with one instance's enabled flag updated."""
    return upsert_feishu_instance(section, defaults, instance_id, {"enabled": enabled})
