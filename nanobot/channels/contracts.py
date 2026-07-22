"""Stable contracts shared by channel runtimes and management surfaces."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from nanobot.channels.plugin import ChannelPlugin

FieldKind = Literal["string", "secret", "list", "bool", "int", "enum"]
RouteFieldType = str | tuple[str, set[str]]


@dataclass(frozen=True, slots=True)
class ChannelValidationContext:
    """Host policy passed to package-owned setup validators."""

    allow_local_service_access: bool = False


SetupValidator = Callable[[dict[str, Any], ChannelValidationContext], dict[str, Any]]
DefaultConfigFactory = Callable[[], dict[str, Any]]
InstanceSpecsFactory = Callable[..., Iterable["ChannelInstanceSpec"]]
InstanceConfigUpdater = Callable[..., dict[str, Any]]
RuntimeNameFactory = Callable[[str, str], str]
FeatureInstancesFactory = Callable[..., list[dict[str, Any]] | None]
LocalStatePresent = Callable[[Any], bool]

__all__ = [
    "ChannelActivation",
    "ChannelFieldSpec",
    "ChannelInstanceSpec",
    "ChannelManagementSpec",
    "ChannelSetupSpec",
    "ChannelValidationContext",
    "SetupRequirement",
    "channel_feature_instances",
    "channel_default_config",
    "channel_field_value",
    "channel_instance_config",
    "channel_instance_specs",
    "channel_local_state_present",
    "channel_runtime_name",
    "resolve_channel_action_target",
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
    channel may expose independently enabled instances. Instance envelopes are
    opt-in so a channel can keep using an ``instances``
    field as ordinary channel-owned configuration.
    """

    enabled: bool | None = None
    instances: tuple["ChannelActivation", ...] | None = None

    @classmethod
    def from_config(
        cls,
        section: Any,
        *,
        include_instances: bool = False,
    ) -> "ChannelActivation":
        values = _config_mapping(section)
        if values is None:
            raw_enabled = getattr(section, "enabled", _MISSING)
            return cls(enabled=None if raw_enabled is _MISSING else bool(raw_enabled))

        raw_enabled = values.get("enabled", _MISSING)
        raw_instances = values.get("instances", _MISSING) if include_instances else _MISSING
        instances = (
            tuple(
                cls.from_config(item, include_instances=True)
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
    default: Any = None
    writable: bool = True
    snapshot: bool = True
    generic_setup: bool = True

    @property
    def route_type(self) -> RouteFieldType:
        if self.kind == "enum":
            return ("enum", set(self.choices))
        return self.kind


@dataclass(frozen=True)
class SetupRequirement:
    """A requirement satisfied by any one complete field group."""

    alternatives: tuple[tuple[str, ...], ...]

    @classmethod
    def field(cls, name: str) -> "SetupRequirement":
        """Require one field."""
        return cls(((name,),))

    @classmethod
    def one_of(cls, *alternatives: tuple[str, ...]) -> "SetupRequirement":
        """Require one complete alternative field group."""
        return cls(alternatives)

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
            if not field.writable or not field.generic_setup:
                continue
            public_field = {
                "key": f"channels.{channel_name}.{name}",
                "field": name,
                "kind": field.kind,
                "choices": sorted(field.choices),
                "required": name in simple_required,
            }
            if field.default is not None:
                public_field["default_value"] = stringify_channel_value(field.default)
            fields.append(public_field)
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
    config: Any


@dataclass(frozen=True)
class ChannelManagementSpec:
    """Dependency-free adapter for persisted channel state.

    Runtime classes own network and message lifecycle only. A multi-instance
    channel supplies these callbacks from a module that can be imported without
    its optional platform SDK.
    """

    multi_instance: bool = False
    default_config: DefaultConfigFactory | None = None
    instance_specs: InstanceSpecsFactory | None = None
    update_instance_config: InstanceConfigUpdater | None = None
    runtime_name: RuntimeNameFactory | None = None
    feature_instances: FeatureInstancesFactory | None = None
    local_state_present: LocalStatePresent | None = None

    def __post_init__(self) -> None:
        multi_instance_callbacks = {
            "instance_specs": self.instance_specs,
            "update_instance_config": self.update_instance_config,
            "runtime_name": self.runtime_name,
            "feature_instances": self.feature_instances,
        }
        if not self.multi_instance:
            unexpected = [
                name for name, callback in multi_instance_callbacks.items() if callback is not None
            ]
            if unexpected:
                raise ValueError(
                    "single-instance channel management cannot define "
                    + ", ".join(unexpected)
                )
        if self.multi_instance and self.instance_specs is None:
            raise ValueError("multi-instance channel management requires instance_specs")
        if self.multi_instance and self.update_instance_config is None:
            raise ValueError("multi-instance channel management requires update_instance_config")


def channel_default_config(plugin: ChannelPlugin) -> dict[str, Any]:
    from nanobot.config.loader import merge_missing_defaults

    defaults: dict[str, Any] = {"enabled": plugin.default_enabled}
    if plugin.setup is not None:
        for name, field in plugin.setup.fields.items():
            value = field.default
            if value is None:
                value = {
                    "string": "",
                    "secret": "",
                    "list": [],
                    "bool": False,
                }.get(field.kind, _MISSING)
            if value is not _MISSING:
                _assign_channel_field(defaults, name, deepcopy(value))

    factory = plugin.management.default_config
    if factory is None:
        return defaults
    values = factory()
    if not isinstance(values, dict):
        raise TypeError(f"ChannelPlugin.management.default_config for '{plugin.name}' must return a dict")
    return merge_missing_defaults(values, defaults)


def _assign_channel_field(values: dict[str, Any], field: str, value: Any) -> None:
    target = values
    parts = field.split(".")
    for part in parts[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[parts[-1]] = value


def channel_local_state_present(plugin: ChannelPlugin, section: Any) -> bool:
    checker = plugin.management.local_state_present
    return bool(checker and checker(section))


def channel_runtime_name(plugin: ChannelPlugin, instance_id: str = "default") -> str:
    factory = plugin.management.runtime_name
    if factory is None:
        if instance_id not in {"", "default"}:
            raise ValueError(f"{plugin.name} does not support multiple instances")
        runtime_name = plugin.name
    else:
        runtime_name = str(factory(plugin.name, instance_id))
    _validate_runtime_name(plugin, runtime_name)
    return runtime_name


def channel_instance_specs(
    plugin: ChannelPlugin,
    section: Any,
    *,
    enabled_only: bool = True,
) -> list[ChannelInstanceSpec]:
    """Expand persisted config through the dependency-free management adapter."""
    factory = plugin.management.instance_specs
    if factory is None:
        activation = ChannelActivation.from_config(section)
        raw_specs: Iterable[ChannelInstanceSpec] = (
            []
            if enabled_only and not activation.resolve(default=plugin.default_enabled)
            else [ChannelInstanceSpec(instance_id="default", config=section)]
        )
    else:
        raw_specs = factory(section, enabled_only=enabled_only)
    if not isinstance(raw_specs, Iterable):
        raise TypeError(
            f"ChannelPlugin.management.instance_specs for '{plugin.name}' must return an iterable"
        )
    specs = list(raw_specs)

    instance_ids: set[str] = set()
    runtime_names: set[str] = set()
    for spec in specs:
        if not isinstance(spec, ChannelInstanceSpec):
            raise TypeError(
                f"ChannelPlugin.management.instance_specs for '{plugin.name}' returned an invalid item"
            )
        if not isinstance(spec.instance_id, str) or not spec.instance_id.strip():
            raise ValueError(
                f"ChannelPlugin.management.instance_specs for '{plugin.name}' returned an empty instance id"
            )
        if spec.instance_id in instance_ids:
            raise ValueError(
                f"ChannelPlugin.management.instance_specs for '{plugin.name}' returned duplicate instance id "
                f"'{spec.instance_id}'"
            )
        runtime_name = channel_runtime_name(plugin, spec.instance_id)
        if runtime_name in runtime_names:
            raise ValueError(
                f"ChannelPlugin.management.instance_specs for '{plugin.name}' returned duplicate runtime name "
                f"'{runtime_name}'"
            )
        instance_ids.add(spec.instance_id)
        runtime_names.add(runtime_name)
    return specs


def resolve_channel_action_target(
    requested_instance_id: str | None,
) -> str:
    """Resolve a feature action to an explicit or default instance."""
    return (requested_instance_id or "").strip() or "default"


def channel_instance_config(
    plugin: ChannelPlugin,
    section: Any,
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    """Return editable config for one instance."""
    selected = next(
        (
            spec
            for spec in channel_instance_specs(plugin, section, enabled_only=False)
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
    plugin: ChannelPlugin,
    section: Any,
    values: dict[str, Any],
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    updater = plugin.management.update_instance_config
    if updater is None:
        if instance_id not in {"", "default"}:
            raise ValueError(f"{plugin.name} does not support multiple instances")
        return values
    return updater(section, values, instance_id=instance_id)


def channel_set_config_enabled(
    plugin: ChannelPlugin,
    section: Any,
    enabled: bool,
    *,
    instance_id: str = "default",
) -> dict[str, Any]:
    """Toggle one instance while preserving channel-owned config shape."""
    from nanobot.config.loader import merge_missing_defaults

    values = channel_instance_config(plugin, section, instance_id=instance_id)
    values = merge_missing_defaults(values, channel_default_config(plugin))
    values["enabled"] = enabled
    return channel_update_instance_config(
        plugin,
        section,
        values,
        instance_id=instance_id,
    )


def channel_feature_instances(
    plugin: ChannelPlugin,
    section: Any,
    *,
    setup_spec: ChannelSetupSpec | None = None,
) -> list[dict[str, Any]] | None:
    factory = plugin.management.feature_instances
    overrides = factory(section, setup_spec=setup_spec) if factory is not None else None
    if overrides is None and not plugin.management.multi_instance:
        return None
    if overrides is not None and (
        not isinstance(overrides, list)
        or any(not isinstance(instance, dict) for instance in overrides)
    ):
        raise TypeError(
            f"ChannelPlugin.management.feature_instances for '{plugin.name}' "
            "must return a list of dicts or None"
        )

    enabled_ids = {
        spec.instance_id for spec in channel_instance_specs(plugin, section, enabled_only=True)
    }

    instances = [
        _channel_feature_instance(
            plugin.name,
            spec,
            setup_spec,
            enabled=spec.instance_id in enabled_ids,
        )
        for spec in channel_instance_specs(plugin, section, enabled_only=False)
    ]
    if overrides is None:
        return instances

    by_id = {instance["id"]: instance for instance in instances}
    seen: set[str] = set()
    for override in overrides:
        instance_id = override.get("id")
        if not isinstance(instance_id, str) or instance_id not in by_id:
            raise ValueError(
                f"ChannelPlugin.management.feature_instances for '{plugin.name}' "
                "returned unknown instance id "
                f"'{instance_id}'"
            )
        if instance_id in seen:
            raise ValueError(
                f"ChannelPlugin.management.feature_instances for '{plugin.name}' "
                "returned duplicate instance id "
                f"'{instance_id}'"
            )
        seen.add(instance_id)
        for field in ("name", "display_name", "avatar_url"):
            if field in override:
                by_id[instance_id][field] = str(override[field] or "")
    return instances


def refresh_channel_feature_metadata(
    channel_cls: type[Any],
    config_path: Path,
    *,
    instance_id: str = "default",
) -> bool:
    return bool(channel_cls.refresh_feature_metadata(config_path, instance_id=instance_id))


def _validate_runtime_name(plugin: ChannelPlugin, runtime_name: Any) -> None:
    channel_name = str(plugin.name).strip()
    if not channel_name:
        raise ValueError("ChannelPlugin.name must not be empty")
    if not isinstance(runtime_name, str) or not runtime_name.strip():
        raise ValueError(f"ChannelPlugin.management for '{plugin.name}' returned an empty runtime name")
    if runtime_name != channel_name and not runtime_name.startswith(f"{channel_name}."):
        raise ValueError(
            f"ChannelPlugin.management runtime name '{runtime_name}' must be scoped under "
            f"'{channel_name}'"
        )


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


def _channel_feature_instance(
    channel_name: str,
    instance: ChannelInstanceSpec,
    setup_spec: ChannelSetupSpec | None,
    *,
    enabled: bool,
) -> dict[str, Any]:
    config = instance.config
    name = str(channel_field_value(config, "name") or instance.instance_id).strip()
    display_name = str(channel_field_value(config, "displayName") or name).strip()
    avatar_url = str(channel_field_value(config, "avatarUrl") or "").strip()
    config_values: dict[str, str] = {}
    configured_fields: list[str] = []
    setup_fields = setup_spec.fields.items() if setup_spec else ()
    for field_name, field_spec in setup_fields:
        if not field_spec.writable:
            continue
        value = channel_field_value(config, field_name)
        if not channel_value_present(value):
            continue
        key = f"channels.{channel_name}.{field_name}"
        configured_fields.append(key)
        if field_spec.kind != "secret":
            config_values[key] = stringify_channel_value(value)

    return {
        "id": instance.instance_id,
        "name": name,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "enabled": enabled,
        "configured": bool(setup_spec and setup_spec.is_configured(config)),
        "config_values": config_values,
        "configured_fields": configured_fields,
    }


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
