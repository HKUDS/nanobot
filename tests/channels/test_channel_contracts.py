"""Shared contract tests for built-in and plugin channel extension points."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelActivation,
    ChannelFieldSpec,
    ChannelSetupSpec,
    SetupRequirement,
    channel_instance_config,
    channel_instance_specs,
    channel_runtime_name,
    channel_set_config_enabled,
    channel_update_instance_config,
)
from nanobot.channels.registry import discover_channel_names


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
    name = "setup-contract"

    @staticmethod
    def _validate(values: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "connected" if values.get("token") else "invalid",
            "checks": [],
        }

    @classmethod
    def setup_spec(cls) -> ChannelSetupSpec:
        return ChannelSetupSpec(
            fields={"token": ChannelFieldSpec(kind="secret")},
            required=(SetupRequirement((("token",),)),),
            validator=cls._validate,
        )


def test_management_contract_does_not_expand_runtime_base_class() -> None:
    management_hooks = {
        "feature_instances",
        "instance_specs",
        "refresh_feature_metadata",
        "runtime_name",
        "setup_spec",
        "update_instance_config",
    }

    assert management_hooks.isdisjoint(BaseChannel.__dict__)


def test_contract_module_is_not_discovered_as_a_channel() -> None:
    assert "contracts" not in discover_channel_names()


@pytest.mark.parametrize(
    ("section", "default", "expected"),
    [
        pytest.param({"enabled": True}, False, True, id="flat-enabled"),
        pytest.param({}, True, True, id="flat-inherits-default"),
        pytest.param(
            {"enabled": False, "instances": [{"enabled": True}]},
            False,
            True,
            id="instance-overrides-parent",
        ),
        pytest.param(
            {"enabled": True, "instances": [{}, {"enabled": False}]},
            False,
            True,
            id="instance-inherits-parent",
        ),
        pytest.param(
            {"enabled": True, "instances": []},
            False,
            False,
            id="empty-instance-list",
        ),
    ],
)
def test_channel_activation_normalizes_persisted_config(
    section: dict[str, Any],
    default: bool,
    expected: bool,
) -> None:
    activation = ChannelActivation.from_config(section)

    assert activation.resolve(default=default) is expected


def _instance_contract_cases():
    from nanobot.channels.feishu import FeishuChannel

    return [
        pytest.param(
            _SingleChannel,
            {"enabled": True, "token": "saved"},
            "default",
            {"default"},
            id="single-instance-default",
        ),
        pytest.param(
            FeishuChannel,
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
    ("channel_cls", "section", "target_id", "expected_ids"),
    _instance_contract_cases(),
)
def test_channel_instance_contract_round_trip(
    channel_cls,
    section,
    target_id,
    expected_ids,
) -> None:
    all_specs = channel_instance_specs(channel_cls, section, enabled_only=False)
    enabled_specs = channel_instance_specs(channel_cls, section)

    assert {spec.instance_id for spec in all_specs} == expected_ids
    assert {spec.instance_id for spec in enabled_specs} == expected_ids
    assert len({spec.runtime_name for spec in all_specs}) == len(all_specs)
    assert all(
        channel_runtime_name(channel_cls, spec.instance_id) == spec.runtime_name
        for spec in all_specs
    )

    disabled = channel_set_config_enabled(
        channel_cls,
        section,
        False,
        instance_id=target_id,
    )
    assert target_id not in {
        spec.instance_id for spec in channel_instance_specs(channel_cls, disabled)
    }

    values = channel_instance_config(channel_cls, disabled, instance_id=target_id)
    values["contractMarker"] = "preserved"
    updated = channel_update_instance_config(
        channel_cls,
        disabled,
        values,
        instance_id=target_id,
    )
    assert channel_instance_config(
        channel_cls,
        updated,
        instance_id=target_id,
    )["contractMarker"] == "preserved"


def test_channel_setup_contract_owns_fields_and_validation() -> None:
    spec = channel_setup_spec(_SetupChannel.name, _SetupChannel)

    assert spec is not None
    assert spec.route_field_types == {"token": "secret"}
    assert spec.is_configured({"token": "saved"}) is True
    assert spec.validator is not None
    assert spec.validator({"token": "saved"})["status"] == "connected"
    assert spec.to_public_dict(_SetupChannel.name) == {
        "fields": [{
            "key": "channels.setup-contract.token",
            "field": "token",
            "kind": "secret",
            "choices": [],
            "required": True,
        }],
    }
