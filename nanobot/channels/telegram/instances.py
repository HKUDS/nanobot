"""Telegram-owned helpers for persisted multi-bot configuration."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from nanobot.channels.contracts import ChannelInstanceSpec, ChannelManagementSpec
from nanobot.channels.telegram.config import telegram_default_config
from nanobot.config.loader import merge_missing_defaults

DEFAULT_INSTANCE_ID = "default"
_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_instance_id(value: str) -> str:
    instance_id = value.strip()
    if not instance_id or not _INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("instance id must match [A-Za-z0-9_-]+")
    return instance_id


def runtime_channel_name(base_name: str, instance_id: str) -> str:
    return base_name if instance_id == DEFAULT_INSTANCE_ID else f"{base_name}.{instance_id}"


def managed_telegram_instance_specs(
    section: Any,
    *,
    enabled_only: bool = True,
) -> list[ChannelInstanceSpec]:
    return telegram_instance_specs(
        section,
        telegram_default_config(),
        enabled_only=enabled_only,
    )


def update_managed_telegram_instance(
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = DEFAULT_INSTANCE_ID,
) -> dict[str, Any]:
    existing = section if isinstance(section, dict) else {}
    return upsert_telegram_instance(
        existing,
        telegram_default_config(),
        instance_id,
        values,
    )


def _base_telegram_instance_config(defaults: dict[str, Any]) -> dict[str, Any]:
    config = dict(defaults)
    config["instanceId"] = DEFAULT_INSTANCE_ID
    config["name"] = "nanobot"
    return config


def _normalize_telegram_instance(
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
    config.setdefault(
        "name",
        "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}",
    )
    return config


def _telegram_instance_inputs(
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
    return ([section] if section else [_base_telegram_instance_config(defaults)]), None


def _webhook_listener(config: dict[str, Any]) -> tuple[str, int] | None:
    mode = str(config.get("mode") or "polling").strip().lower()
    if mode != "webhook":
        return None

    host = str(
        config.get("webhookListenHost")
        or config.get("webhook_listen_host")
        or "127.0.0.1"
    ).strip().lower()
    raw_port = config.get(
        "webhookListenPort",
        config.get("webhook_listen_port", 8081),
    )
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("webhookListenPort must be an integer") from exc
    return host, port


def telegram_instance_specs(
    section: Any,
    defaults: dict[str, Any],
    *,
    enabled_only: bool = False,
) -> list[ChannelInstanceSpec]:
    """Expand legacy or canonical Telegram config into runtime bot specs."""
    raw_specs, inherited = _telegram_instance_inputs(section, defaults)

    specs: list[ChannelInstanceSpec] = []
    instance_ids: set[str] = set()
    token_owners: dict[str, str] = {}
    webhook_owners: dict[tuple[str, int], str] = {}
    for index, raw in enumerate(raw_specs):
        if not isinstance(raw, dict):
            logger.warning("Skipping invalid Telegram instance at index {}: expected an object", index)
            continue
        fallback_id = DEFAULT_INSTANCE_ID if index == 0 else f"bot-{index + 1}"
        try:
            config = _normalize_telegram_instance(
                raw,
                defaults,
                inherited=inherited,
                fallback_id=fallback_id,
            )
        except ValueError as exc:
            logger.warning("Skipping invalid Telegram instance config: {}", exc)
            continue

        instance_id = str(config["instanceId"])
        if instance_id in instance_ids:
            logger.warning("Skipping duplicate Telegram instance id '{}'", instance_id)
            continue
        instance_ids.add(instance_id)

        enabled = bool(config.get("enabled", defaults.get("enabled", False)))
        if enabled_only and not enabled:
            continue

        token = str(config.get("token") or "").strip()
        if enabled_only and token:
            if token in token_owners:
                logger.warning(
                    "Skipping Telegram instance '{}' because it uses the same bot token as instance '{}'",
                    instance_id,
                    token_owners[token],
                )
                continue

        listener: tuple[str, int] | None = None
        if enabled_only:
            try:
                listener = _webhook_listener(config)
            except ValueError as exc:
                logger.warning(
                    "Skipping Telegram instance '{}' because its webhook listener is invalid: {}",
                    instance_id,
                    exc,
                )
                continue
            if listener is not None:
                if listener in webhook_owners:
                    host, port = listener
                    logger.warning(
                        "Skipping Telegram instance '{}' because webhook listener {}:{} is already used by instance '{}'",
                        instance_id,
                        host,
                        port,
                        webhook_owners[listener],
                    )
                    continue

        if enabled_only and token:
            token_owners[token] = instance_id
        if listener is not None:
            webhook_owners[listener] = instance_id

        specs.append(ChannelInstanceSpec(instance_id=instance_id, config=config))

    return specs


def canonical_telegram_section(section: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Return canonical multi-bot config without losing legacy values."""
    raw_specs, inherited = _telegram_instance_inputs(section, defaults)
    instances: list[dict[str, Any]] = []
    instance_ids: set[str] = set()
    token_owners: dict[str, str] = {}
    webhook_owners: dict[tuple[str, int], str] = {}

    for index, raw in enumerate(raw_specs):
        if not isinstance(raw, dict):
            raise ValueError(f"Telegram instance at index {index} must be an object")
        fallback_id = DEFAULT_INSTANCE_ID if index == 0 else f"bot-{index + 1}"
        try:
            config = _normalize_telegram_instance(
                raw,
                defaults,
                inherited=inherited,
                fallback_id=fallback_id,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram instance at index {index}: {exc}") from exc

        instance_id = str(config["instanceId"])
        if instance_id in instance_ids:
            raise ValueError(f"duplicate Telegram instance id '{instance_id}'")
        instance_ids.add(instance_id)

        token = str(config.get("token") or "").strip()
        if token:
            if token in token_owners:
                raise ValueError("Telegram bot token is already used by another instance")
            token_owners[token] = instance_id

        if bool(config.get("enabled", defaults.get("enabled", False))):
            listener = _webhook_listener(config)
            if listener is not None:
                if listener in webhook_owners:
                    host, port = listener
                    owner = webhook_owners[listener]
                    raise ValueError(
                        f"Telegram webhook listener {host}:{port} is already used by instance "
                        f"'{owner}'"
                    )
                webhook_owners[listener] = instance_id
        instances.append(config)

    return {"instances": instances}


def upsert_telegram_instance(
    section: Any,
    defaults: dict[str, Any],
    instance_id: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Create or update one bot and migrate legacy flat config when necessary."""
    instance_id = validate_instance_id(instance_id)
    canonical = canonical_telegram_section(section, defaults)
    instances = canonical.setdefault("instances", [])

    for instance in instances:
        if instance.get("id") == instance_id or instance.get("instanceId") == instance_id:
            instance.update(values)
            instance["id"] = instance_id
            instance["instanceId"] = instance_id
            instance.setdefault(
                "name",
                "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}",
            )
            return canonical_telegram_section(canonical, defaults)

    config = _normalize_telegram_instance(
        {**values, "id": instance_id},
        defaults,
        fallback_id=instance_id,
    )
    instances.append(config)
    return canonical_telegram_section(canonical, defaults)


TELEGRAM_MANAGEMENT = ChannelManagementSpec(
    multi_instance=True,
    default_config=telegram_default_config,
    instance_specs=managed_telegram_instance_specs,
    update_instance_config=update_managed_telegram_instance,
    runtime_name=runtime_channel_name,
)


__all__ = [
    "DEFAULT_INSTANCE_ID",
    "TELEGRAM_MANAGEMENT",
    "canonical_telegram_section",
    "runtime_channel_name",
    "telegram_instance_specs",
    "upsert_telegram_instance",
    "validate_instance_id",
]
