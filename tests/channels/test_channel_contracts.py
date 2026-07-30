"""Shared contract tests for self-contained channel packages."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelActivation,
    ChannelFieldSpec,
    ChannelInstanceSpec,
    ChannelManagementSpec,
    ChannelSetupSpec,
    ChannelValidationContext,
    SetupRequirement,
    channel_feature_instances,
    channel_instance_config,
    channel_instance_specs,
    channel_runtime_name,
    channel_set_config_enabled,
    channel_update_instance_config,
    resolve_channel_action_target,
)
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.registry import discover_plugins, load_channel_plugin


class _SingleChannel(BaseChannel):
    name = "single"
    display_name = "Single"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "token": ""}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


class _SetupChannel(_SingleChannel):
    name = "setup_contract"

    @staticmethod
    def _validate(
        values: dict[str, Any],
        _context: ChannelValidationContext,
    ) -> dict[str, Any]:
        return {
            "status": "connected" if values.get("token") else "invalid",
            "checks": [],
        }



_SETUP_PLUGIN = ChannelPlugin(
    name=_SetupChannel.name,
    display_name=_SetupChannel.display_name,
    runtime=f"{__name__}:_SetupChannel",
    setup=ChannelSetupSpec(
        fields={"token": ChannelFieldSpec(kind="secret")},
        required=(SetupRequirement((("token",),)),),
        validator=_SetupChannel._validate,
    ),
)

_SINGLE_PLUGIN = ChannelPlugin(
    name=_SingleChannel.name,
    display_name=_SingleChannel.display_name,
    runtime=f"{__name__}:_SingleChannel",
    management=ChannelManagementSpec(default_config=_SingleChannel.default_config),
)


def test_management_contract_is_not_declared_on_runtime_base_class() -> None:
    management_hooks = {
        "feature_instances",
        "instance_specs",
        "runtime_name",
        "supports_multiple_instances",
        "update_instance_config",
    }

    assert management_hooks.isdisjoint(BaseChannel.__dict__.keys())
    assert "refresh_feature_metadata" in BaseChannel.__dict__


def test_multi_instance_support_is_declared_by_management_spec() -> None:
    assert _SINGLE_PLUGIN.management.multi_instance is False
    assert load_channel_plugin("feishu").management.multi_instance is True


@pytest.mark.parametrize(
    "callback",
    [
        "instance_specs",
        "update_instance_config",
        "runtime_name",
        "feature_instances",
    ],
)
def test_single_instance_management_rejects_multi_instance_callbacks(callback: str) -> None:
    with pytest.raises(ValueError, match=callback):
        ChannelManagementSpec(**{callback: lambda *args, **kwargs: None})


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        pytest.param(None, "default", id="default-instance"),
        pytest.param("product", "product", id="explicit-instance"),
    ],
)
def test_channel_action_target_contract(
    requested,
    expected,
) -> None:
    assert resolve_channel_action_target(requested) == expected


def test_contract_module_is_not_discovered_as_a_channel() -> None:
    assert "contracts" not in discover_plugins()
    assert "manifests" not in discover_plugins()


def test_settings_contract_import_does_not_eagerly_load_runtime_graph() -> None:
    code = """
import sys
import nanobot.channels.validation

unexpected = {
    "nanobot.channels.manager",
    "nanobot.channels.websocket",
    "nanobot.webui.gateway_services",
} & sys.modules.keys()
assert not unexpected, sorted(unexpected)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("section", "default", "include_instances", "expected"),
    [
        pytest.param({"enabled": True}, False, False, True, id="flat-enabled"),
        pytest.param({}, True, False, True, id="flat-inherits-default"),
        pytest.param(
            {"enabled": True, "instances": ["plugin-owned-value"]},
            False,
            False,
            True,
            id="single-instance-plugin-owns-instances-field",
        ),
        pytest.param(
            {"enabled": False, "instances": [{"enabled": True}]},
            False,
            True,
            True,
            id="instance-overrides-parent",
        ),
        pytest.param(
            {"enabled": True, "instances": [{}, {"enabled": False}]},
            False,
            True,
            True,
            id="instance-inherits-parent",
        ),
        pytest.param(
            {"enabled": True, "instances": []},
            False,
            True,
            False,
            id="empty-instance-list",
        ),
    ],
)
def test_channel_activation_normalizes_persisted_config(
    section: dict[str, Any],
    default: bool,
    include_instances: bool,
    expected: bool,
) -> None:
    activation = ChannelActivation.from_config(
        section,
        include_instances=include_instances,
    )

    assert activation.resolve(default=default) is expected


def _instance_contract_cases():
    return [
        pytest.param(
            _SINGLE_PLUGIN,
            {"enabled": True, "token": "saved"},
            "default",
            {"default"},
            id="single-instance-default",
        ),
        pytest.param(
            load_channel_plugin("feishu"),
            {
                "instances": [
                    {
                        "id": "default",
                        "enabled": True,
                        "appId": "cli_default",
                        "appSecret": "secret",
                    },
                    {
                        "id": "product",
                        "enabled": True,
                        "appId": "cli_product",
                        "appSecret": "secret",
                    },
                ]
            },
            "product",
            {"default", "product"},
            id="feishu-multi-instance",
        ),
    ]


@pytest.mark.parametrize(
    ("plugin", "section", "target_id", "expected_ids"),
    _instance_contract_cases(),
)
def test_channel_instance_contract_round_trip(
    plugin,
    section,
    target_id,
    expected_ids,
) -> None:
    all_specs = channel_instance_specs(plugin, section, enabled_only=False)
    enabled_specs = channel_instance_specs(plugin, section)

    assert {spec.instance_id for spec in all_specs} == expected_ids
    assert {spec.instance_id for spec in enabled_specs} == expected_ids
    runtime_names = {channel_runtime_name(plugin, spec.instance_id) for spec in all_specs}
    assert len(runtime_names) == len(all_specs)

    disabled = channel_set_config_enabled(
        plugin,
        section,
        False,
        instance_id=target_id,
    )
    assert target_id not in {
        spec.instance_id for spec in channel_instance_specs(plugin, disabled)
    }

    values = channel_instance_config(plugin, disabled, instance_id=target_id)
    values["contractMarker"] = "preserved"
    updated = channel_update_instance_config(
        plugin,
        disabled,
        values,
        instance_id=target_id,
    )
    assert channel_instance_config(
        plugin,
        updated,
        instance_id=target_id,
    )["contractMarker"] == "preserved"


def test_channel_feature_instances_use_generic_setup_snapshot() -> None:
    setup_spec = ChannelSetupSpec(
        fields={
            "token": ChannelFieldSpec(kind="secret"),
            "region": ChannelFieldSpec(kind="enum", choices=frozenset({"eu", "us"})),
            "topicIsolation": ChannelFieldSpec(kind="bool"),
        },
        required=(SetupRequirement.field("token"),),
    )
    plugin = ChannelPlugin(
        name="feature_multi",
        display_name="Feature multi",
        runtime=f"{__name__}:_SingleChannel",
        setup=setup_spec,
        management=ChannelManagementSpec(
            multi_instance=True,
            instance_specs=lambda section, *, enabled_only=True: [
                ChannelInstanceSpec(item["id"], item)
                for item in section["instances"]
                if not enabled_only or item["enabled"]
            ],
            update_instance_config=lambda section, values, *, instance_id="default": section,
            runtime_name=lambda name, instance_id: (
                name if instance_id == "default" else f"{name}.{instance_id}"
            ),
            feature_instances=lambda section, *, setup_spec=None: [{
                "id": "product",
                "display_name": "Catalog product helper",
                "enabled": False,
                "config_values": {"channels.feature_multi.token": "leaked"},
            }],
        ),
    )
    section = {
        "instances": [
            {
                "id": "product",
                "name": "Product bot",
                "displayName": "Product helper",
                "avatarUrl": "https://example.com/product.png",
                "enabled": True,
                "token": "secret",
                "region": "eu",
                "topicIsolation": False,
            }
        ]
    }

    instances = channel_feature_instances(
        plugin,
        section,
        setup_spec=setup_spec,
    )

    assert instances == [
        {
            "id": "product",
            "name": "Product bot",
            "display_name": "Catalog product helper",
            "avatar_url": "https://example.com/product.png",
            "enabled": True,
            "configured": True,
            "config_values": {
                "channels.feature_multi.region": "eu",
                "channels.feature_multi.topicIsolation": "false",
            },
            "configured_fields": [
                "channels.feature_multi.token",
                "channels.feature_multi.region",
                "channels.feature_multi.topicIsolation",
            ],
        }
    ]


def test_feishu_instance_contract_skips_duplicate_app_identity() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret",
                "domain": "feishu",
            },
            {
                "id": "assistant-copy",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret",
                "domain": "feishu",
            },
        ]
    }

    specs = channel_instance_specs(load_channel_plugin("feishu"), section)

    assert [spec.instance_id for spec in specs] == ["default"]


def test_feishu_feature_state_matches_runtime_duplicate_filter() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret",
                "domain": "feishu",
            },
            {
                "id": "assistant-copy",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret",
                "domain": "feishu",
            },
        ]
    }

    instances = channel_feature_instances(
        load_channel_plugin("feishu"),
        section,
        setup_spec=channel_setup_spec("feishu"),
    )

    assert instances is not None
    assert [(item["id"], item["enabled"]) for item in instances] == [
        ("default", True),
        ("assistant-copy", False),
    ]


def test_feishu_runtime_duplicate_ignores_disabled_identity_owner() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": False,
                "appId": "cli_same",
                "appSecret": "secret-a",
                "domain": "feishu",
            },
            {
                "id": "assistant-copy",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret-b",
                "domain": "feishu",
            },
        ]
    }

    specs = channel_instance_specs(load_channel_plugin("feishu"), section)

    assert [spec.instance_id for spec in specs] == ["assistant-copy"]


def test_feishu_instance_write_preserves_duplicate_app_identity() -> None:
    section = {
        "instances": [
            {
                "id": "default",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret-a",
            },
            {
                "id": "assistant-copy",
                "enabled": True,
                "appId": "cli_same",
                "appSecret": "secret-b",
            },
        ]
    }

    updated = channel_set_config_enabled(
        load_channel_plugin("feishu"),
        section,
        False,
        instance_id="assistant-copy",
    )

    assert [instance["id"] for instance in updated["instances"]] == [
        "default",
        "assistant-copy",
    ]
    assert updated["instances"][0]["appSecret"] == "secret-a"
    assert updated["instances"][1]["appId"] == "cli_same"
    assert updated["instances"][1]["appSecret"] == "secret-b"
    assert updated["instances"][1]["enabled"] is False


def test_channel_instance_contract_materializes_generators() -> None:
    def generate_specs(section, *, enabled_only=True):
        yield ChannelInstanceSpec("default", section)
        yield ChannelInstanceSpec("product", section)

    plugin = ChannelPlugin(
        name="generated",
        display_name="Generated",
        runtime=f"{__name__}:_SingleChannel",
        setup=ChannelSetupSpec(fields={}),
        management=ChannelManagementSpec(
            multi_instance=True,
            instance_specs=generate_specs,
            update_instance_config=lambda section, values, *, instance_id="default": values,
            runtime_name=lambda name, instance_id: (
                name if instance_id == "default" else f"{name}.{instance_id}"
            ),
        ),
    )

    specs = channel_instance_specs(plugin, {"enabled": True})

    assert [spec.instance_id for spec in specs] == ["default", "product"]


def test_single_instance_contract_preserves_plugin_owned_instances_field() -> None:
    section = {
        "enabled": True,
        "instances": ["plugin-owned-value"],
    }

    specs = channel_instance_specs(_SINGLE_PLUGIN, section)

    assert specs == [ChannelInstanceSpec("default", section)]


@pytest.mark.parametrize(
    ("instance_ids", "message"),
    [
        pytest.param(
            ["default", "default"],
            "duplicate instance id 'default'",
            id="duplicate-instance-id",
        ),
        pytest.param(
            ["default", "product"],
            "duplicate runtime name 'invalid'",
            id="duplicate-runtime-name",
        ),
    ],
)
def test_channel_instance_contract_rejects_invalid_specs(instance_ids, message) -> None:
    plugin = ChannelPlugin(
        name="invalid",
        display_name="Invalid",
        runtime=f"{__name__}:_SingleChannel",
        setup=ChannelSetupSpec(fields={}),
        management=ChannelManagementSpec(
            multi_instance=True,
            instance_specs=lambda section, *, enabled_only=True: [
                ChannelInstanceSpec(instance_id, {}) for instance_id in instance_ids
            ],
            update_instance_config=lambda section, values, *, instance_id="default": values,
            runtime_name=lambda name, instance_id: name,
        ),
    )

    with pytest.raises(ValueError, match=message):
        channel_instance_specs(plugin, {"enabled": True})


def test_channel_instance_contract_rejects_runtime_name_outside_namespace() -> None:
    plugin = ChannelPlugin(
        name="invalid",
        display_name="Invalid",
        runtime=f"{__name__}:_SingleChannel",
        setup=ChannelSetupSpec(fields={}),
        management=ChannelManagementSpec(
            multi_instance=True,
            instance_specs=lambda section, *, enabled_only=True: [
                ChannelInstanceSpec("default", section)
            ],
            update_instance_config=lambda section, values, *, instance_id="default": values,
            runtime_name=lambda name, instance_id: "other",
        ),
    )

    with pytest.raises(ValueError, match="must be scoped under 'invalid'"):
        channel_instance_specs(plugin, {"enabled": True})


def test_channel_setup_contract_owns_fields_and_validation() -> None:
    spec = channel_setup_spec(
        _SetupChannel.name,
        plugin=_SETUP_PLUGIN,
    )

    assert spec is not None
    assert spec.route_field_types == {"token": "secret"}
    assert spec.is_configured({"token": "saved"}) is True
    assert spec.validator is not None
    assert spec.validator({"token": "saved"}, ChannelValidationContext())["status"] == "connected"
    assert spec.to_public_dict(_SetupChannel.name) == {
        "fields": [{
            "key": "channels.setup_contract.token",
            "field": "token",
            "kind": "secret",
            "choices": [],
            "required": True,
        }],
    }
