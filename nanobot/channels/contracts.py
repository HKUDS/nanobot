"""Stable contracts shared by channel runtimes and management surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

FieldKind = Literal["string", "secret", "list", "bool", "int", "enum"]
RouteFieldType = str | tuple[str, set[str]]
SetupValidator = Callable[[dict[str, Any]], dict[str, Any]]

__all__ = [
    "ChannelActivation",
    "ChannelFieldSpec",
    "ChannelInstanceSpec",
    "ChannelSetupSpec",
    "SetupRequirement",
    "channel_feature_instances",
    "channel_field_value",
    "channel_instance_config",
    "channel_instance_specs",
    "channel_runtime_name",
    "channel_set_config_enabled",
    "channel_update_instance_config",
    "channel_value_present",
    "refresh_channel_feature_metadata",
    "stringify_channel_value",
]


_MISSING = object()


@dataclass(frozen=True)
class ChannelActivation:
    """Normalized enablement state used before a channel runtime is imported.

    Channel configuration may be a Pydantic model or persisted JSON, and a
    channel may expose independently enabled instances.  Parse that storage
    shape once here so discovery code never needs to inspect raw config keys.
    """

    enabled: bool | None = None
    instances: tuple["ChannelActivation", ...] | None = None

    @classmethod
    def from_config(cls, section: Any) -> "ChannelActivation":
        values = _config_mapping(section)
        if values is None:
            raw_enabled = getattr(section, "enabled", _MISSING)
            return cls(enabled=None if raw_enabled is _MISSING else bool(raw_enabled))

        raw_enabled = values.get("enabled", _MISSING)
        raw_instances = values.get("instances", _MISSING)
        instances = (
            tuple(
                cls.from_config(item)
                for item in raw_instances
                if _config_mapping(item) is not None
            )
            if isinstance(raw_instances, list)
            else None
        )
        return cls(
            enabled=None if raw_enabled is _MISSING else bool(raw_enabled),
            instances=instances,
        )

    def resolve(self, *, default: bool = False) -> bool:
        """Return whether the section contains at least one enabled runtime."""
        inherited = default if self.enabled is None else self.enabled
        if self.instances is None:
            return inherited
        return any(instance.resolve(default=inherited) for instance in self.instances)


@dataclass(frozen=True)
class ChannelFieldSpec:
    """One channel field exposed through the settings contract."""

    kind: FieldKind = "string"
    choices: frozenset[str] = frozenset()
    writable: bool = True
    snapshot: bool = True

    @property
    def route_type(self) -> RouteFieldType:
        if self.kind == "enum":
            return ("enum", set(self.choices))
        return self.kind


@dataclass(frozen=True)
class SetupRequirement:
    """A requirement satisfied by any one complete field group."""

    alternatives: tuple[tuple[str, ...], ...]

    def is_satisfied(self, values: Any) -> bool:
        return any(
            all(channel_value_present(channel_field_value(values, field)) for field in group)
            for group in self.alternatives
        )

    @property
    def simple_field(self) -> str | None:
        if len(self.alternatives) == 1 and len(self.alternatives[0]) == 1:
            return self.alternatives[0][0]
        return None


@dataclass(frozen=True)
class ChannelSetupSpec:
    """Writable setup fields, requirements, and optional validation."""

    fields: dict[str, ChannelFieldSpec]
    required: tuple[SetupRequirement, ...] = ()
    official_url: str | None = None
    multi_instance: bool = False
    validator: SetupValidator | None = None

    @property
    def secrets(self) -> frozenset[str]:
        return frozenset(name for name, field in self.fields.items() if field.kind == "secret")

    @property
    def snapshot_fields(self) -> tuple[str, ...]:
        return tuple(name for name, field in self.fields.items() if field.snapshot)

    @property
    def route_field_types(self) -> dict[str, RouteFieldType]:
        return {
            name: field.route_type
            for name, field in self.fields.items()
            if field.writable
        }

    @property
    def simple_required_fields(self) -> tuple[str, ...]:
        return tuple(
            field
            for requirement in self.required
            if (field := requirement.simple_field) is not None
        )

    def is_configured(self, values: Any) -> bool:
        return bool(self.required) and all(
            requirement.is_satisfied(values) for requirement in self.required
        )

    def to_public_dict(self, channel_name: str) -> dict[str, Any]:
        """Serialize the writable setup contract for generic WebUI consumers."""
        simple_required = set(self.simple_required_fields)
        fields = []
        for name, field in self.fields.items():
            if not field.writable:
                continue
            fields.append(
                {
                    "key": f"channels.{channel_name}.{name}",
                    "field": name,
                    "kind": field.kind,
                    "choices": sorted(field.choices),
                    "required": name in simple_required,
                }
            )
        payload: dict[str, Any] = {
            "fields": fields,
        }
        if self.official_url:
            payload["official_url"] = self.official_url
        return payload


@dataclass(frozen=True)
class ChannelInstanceSpec:
    """One independently managed runtime instance."""

    instance_id: str
    runtime_name: str
    config: Any


def channel_runtime_name(channel_cls: type[Any], instance_id: str = "default") -> str:
    provider = getattr(channel_cls, "runtime_name", None)
    if callable(provider):
        return str(provider(instance_id))
    if instance_id not in {"", "default"}:
        raise ValueError(f"{channel_cls.name} does not support multiple instances")
    return str(channel_cls.name)


def channel_instance_specs(
    channel_cls: type[Any],
    section: Any,
    *,
    enabled_only: bool = True,
) -> list[ChannelInstanceSpec]:
    """Expand persisted config through a channel override or the single-instance default."""
    provider = getattr(channel_cls, "instance_specs", None)
    if callable(provider):
        specs = provider(section, enabled_only=enabled_only)
        if not all(isinstance(spec, ChannelInstanceSpec) for spec in specs):
            raise TypeError(f"{channel_cls.__name__}.instance_specs() returned an invalid item")
        return specs

    enabled = (
        bool(section.get("enabled", False))
        if isinstance(section, dict)
        else bool(getattr(section, "enabled", False))
    )
    if enabled_only and not enabled:
        return []
    return [
        ChannelInstanceSpec(
            instance_id="default",
            runtime_name=channel_runtime_name(channel_cls),
            config=section,
        )
    ]


def channel_instance_config(
    channel_cls: type[Any],
    section: Any,
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    """Return editable config for one instance."""
    selected = next(
        (
            spec
            for spec in channel_instance_specs(channel_cls, section, enabled_only=False)
            if spec.instance_id == instance_id
        ),
        None,
    )
    if selected is None:
        return {}
    config = selected.config
    if hasattr(config, "model_dump"):
        return dict(config.model_dump(mode="json", by_alias=True))
    return dict(config) if isinstance(config, dict) else {}


def channel_update_instance_config(
    channel_cls: type[Any],
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    provider = getattr(channel_cls, "update_instance_config", None)
    if callable(provider):
        return provider(section, values, instance_id=instance_id)
    if instance_id not in {"", "default"}:
        raise ValueError(f"{channel_cls.name} does not support multiple instances")
    return values


def channel_set_config_enabled(
    channel_cls: type[Any],
    section: Any,
    enabled: bool,
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    """Toggle one instance while preserving channel-owned config shape."""
    from nanobot.config.loader import merge_missing_defaults

    values = channel_instance_config(channel_cls, section, instance_id=instance_id)
    values = merge_missing_defaults(values, channel_cls.default_config())
    values["enabled"] = enabled
    return channel_update_instance_config(
        channel_cls,
        section,
        values,
        instance_id=instance_id,
    )


def channel_feature_instances(
    channel_cls: type[Any],
    section: Any,
    *,
    setup_spec: ChannelSetupSpec | None = None,
) -> list[dict[str, Any]] | None:
    provider = getattr(channel_cls, "feature_instances", None)
    return (
        provider(section, setup_spec=setup_spec)
        if callable(provider)
        else None
    )


def refresh_channel_feature_metadata(
    channel_cls: type[Any],
    config_path: Path,
    *,
    instance_id: str = "default",
) -> bool:
    provider = getattr(channel_cls, "refresh_feature_metadata", None)
    return bool(provider(config_path, instance_id=instance_id)) if callable(provider) else False


def channel_field_value(values: Any, field_path: str) -> Any:
    current = values
    for part in field_path.split("."):
        candidates = (part, _camel_to_snake(part))
        if isinstance(current, dict):
            for candidate in candidates:
                if candidate in current:
                    current = current[candidate]
                    break
            else:
                return None
            continue
        for candidate in candidates:
            if hasattr(current, candidate):
                current = getattr(current, candidate)
                break
        else:
            return None
    return current


def channel_value_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def stringify_channel_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _config_mapping(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", by_alias=True)
        return dumped if isinstance(dumped, dict) else None
    return value if isinstance(value, dict) else None


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char.isupper():
            if chars:
                chars.append("_")
            chars.append(char.lower())
        else:
            chars.append(char)
    return "".join(chars)
