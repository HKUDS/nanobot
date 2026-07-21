"""Tests for channel package discovery, management, and config behavior."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tomllib
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelFieldSpec,
    ChannelInstanceSpec,
    ChannelManagementSpec,
    ChannelSetupSpec,
    SetupRequirement,
    channel_default_config,
)
from nanobot.channels.manager import ChannelManager
from nanobot.channels.plugin import ChannelPlugin, load_channel_package
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import ChannelsConfig, Config
from nanobot.providers.transcription import GroqTranscriptionProvider as _GroqProvider
from nanobot.providers.transcription import OpenAITranscriptionProvider as _OpenAIProvider
from nanobot.utils.restart import RestartNotice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePlugin(BaseChannel):
    name = "fakeplugin"
    display_name = "Fake Plugin"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.login_calls: list[bool] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass

    async def login(self, force: bool = False) -> bool:
        self.login_calls.append(force)
        return True


class _SetupPlugin(_FakePlugin):
    name = "setupplugin"
    display_name = "Setup Plugin"

    @staticmethod
    def _validate_setup(values, _context):
        token = str(values.get("token") or "")
        return {
            "status": "connected" if token.startswith("plugin-") else "invalid",
            "checks": [{
                "id": "plugin",
                "label": "Plugin validation",
                "status": "pass" if token.startswith("plugin-") else "fail",
            }],
        }


class _FakeLine(_FakePlugin):
    name = "line"
    display_name = "Line"


class _FakeMultiChannel(BaseChannel):
    name = "multi"
    display_name = "Multi"

    @classmethod
    def default_config(cls) -> dict:
        return {
            "instanceId": "default",
            "name": "nanobot",
            "enabled": False,
            "token": "",
        }

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


def _fake_multi_instance_specs(section, *, enabled_only=True):
    instances = section.get("instances", []) if isinstance(section, dict) else []
    return [
        ChannelInstanceSpec(
            instance_id=item["id"],
            config=item,
        )
        for item in instances
        if not enabled_only or item.get("enabled", False)
    ]


def _fake_multi_update(section, values, *, instance_id="default"):
    updated = dict(section)
    instances = [dict(item) for item in section.get("instances", [])]
    for item in instances:
        if item.get("id") == instance_id:
            item.update(values)
            break
    updated["instances"] = instances
    return updated


def _fake_multi_management() -> ChannelManagementSpec:
    return ChannelManagementSpec(
        multi_instance=True,
        default_config=_FakeMultiChannel.default_config,
        instance_specs=_fake_multi_instance_specs,
        update_instance_config=_fake_multi_update,
        runtime_name=lambda name, instance_id: (
            name if instance_id == "default" else f"{name}.{instance_id}"
        ),
    )


def _channel_plugin(
    channel_cls: type[BaseChannel],
    *,
    setup: ChannelSetupSpec | None = None,
    dependencies: tuple[str, ...] = (),
    default_enabled: bool = False,
    management: ChannelManagementSpec | None = None,
) -> ChannelPlugin:
    """Create a descriptor whose lazy runtime resolves inside this test module."""
    runtime_attr = f"_runtime_{channel_cls.name.replace('-', '_')}"
    globals()[runtime_attr] = channel_cls
    if management is None:
        management = (
            _fake_multi_management()
            if issubclass(channel_cls, _FakeMultiChannel)
            else ChannelManagementSpec(default_config=channel_cls.default_config)
        )
    if setup is None and management.multi_instance:
        setup = ChannelSetupSpec(fields={})
    return ChannelPlugin(
        name=channel_cls.name,
        display_name=channel_cls.display_name,
        runtime=f"{__name__}:{runtime_attr}",
        setup=setup,
        management=management,
        dependencies=dependencies,
        default_enabled=default_enabled,
    )


_SETUP_PLUGIN_SPEC = ChannelSetupSpec(
    fields={
        "token": ChannelFieldSpec(kind="secret"),
        "region": ChannelFieldSpec(
            kind="enum",
            choices=frozenset({"us", "eu"}),
        ),
    },
    required=(SetupRequirement((("token",),)),),
    official_url="https://plugin.example/setup",
    validator=_SetupPlugin._validate_setup,
)


def _stub_channel_registry(
    monkeypatch: pytest.MonkeyPatch,
    *plugins: ChannelPlugin,
) -> None:
    by_name = {plugin.name: plugin for plugin in plugins}

    def discover(enabled_names=None):
        if enabled_names is None:
            return dict(by_name)
        return {name: plugin for name, plugin in by_name.items() if name in enabled_names}

    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", discover)


def _stub_channel_packages(
    monkeypatch: pytest.MonkeyPatch,
    *names: str,
) -> None:
    from nanobot.channels.plugin import load_channel_package

    plugins = [load_channel_package(name) for name in names]
    assert all(plugin is not None for plugin in plugins)
    _stub_channel_registry(monkeypatch, *(plugin for plugin in plugins if plugin is not None))


def _stub_optional_feature_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    extras: dict[str, list[str] | None],
    installed: bool,
    commands: list[list[str]] | None = None,
    channels: list[str] | None = None,
    channel_cls: type[BaseChannel] | None = None,
) -> None:
    plugins = []
    if channel_cls is not None:
        plugins.append(
            _channel_plugin(
                channel_cls,
                dependencies=tuple(extras.get(channel_cls.name) or ()),
            )
        )
    assert not channels or {plugin.name for plugin in plugins} == set(channels)
    _stub_channel_registry(monkeypatch, *plugins)
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: extras)
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: installed)
    if commands is not None:
        monkeypatch.setattr(
            "nanobot.optional_features.run_install_command",
            lambda argv: commands.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""),
        )


# ---------------------------------------------------------------------------
# ChannelsConfig extra="allow"
# ---------------------------------------------------------------------------

def test_channels_config_accepts_unknown_keys():
    cfg = ChannelsConfig.model_validate({
        "myplugin": {"enabled": True, "token": "abc"},
    })
    extra = cfg.model_extra
    assert extra is not None
    assert extra["myplugin"]["enabled"] is True
    assert extra["myplugin"]["token"] == "abc"


def test_channels_config_getattr_returns_extra():
    cfg = ChannelsConfig.model_validate({"myplugin": {"enabled": True}})
    section = getattr(cfg, "myplugin", None)
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_channels_config_has_no_per_channel_fields():
    """After decoupling, ChannelsConfig has no explicit channel fields."""
    cfg = ChannelsConfig()
    assert not hasattr(cfg, "telegram")
    assert cfg.send_progress is True
    assert cfg.send_tool_hints is False
    assert cfg.extract_document_text is True


def test_channels_config_extract_document_text_accepts_camel_alias():
    cfg = ChannelsConfig.model_validate({"extractDocumentText": False})

    assert cfg.extract_document_text is False


@pytest.mark.parametrize(
    "name",
    ["websocket", "telegram", "discord", "slack", "email", "feishu", "matrix", "weixin", "whatsapp"],
)
def test_special_setup_validation_is_owned_by_channel_package(name: str):
    plugin = load_channel_package(name)

    assert plugin is not None
    assert plugin.setup is not None
    assert plugin.setup.validator is not None
    assert plugin.setup.validator.__module__ == f"nanobot.channels.{name}.validation"


@pytest.mark.parametrize("name", ["feishu", "weixin"])
def test_interactive_connector_is_owned_by_channel_package(name: str):
    plugin = load_channel_package(name)

    assert plugin is not None
    assert plugin.connector is not None
    assert plugin.connector.startswith(f"nanobot.channels.{name}.")
    assert plugin.load_connector().__class__.__module__ == f"nanobot.channels.{name}.connect"


def test_descriptor_defaults_cover_onboarding_fields_without_runtime_import():
    qq = load_channel_package("qq")
    email = load_channel_package("email")

    assert qq is not None
    assert email is not None
    assert channel_default_config(qq)["msgFormat"] == "plain"
    assert channel_default_config(email)["imapPort"] == 993
    assert channel_default_config(email)["smtpPort"] == 587


def test_channel_manager_delegates_instance_expansion_to_channel(monkeypatch: pytest.MonkeyPatch):
    _stub_channel_registry(monkeypatch, _channel_plugin(_FakeMultiChannel))

    cfg = Config.model_validate({
        "channels": {
            "multi": {
                "enabled": True,
                "instances": [
                    {
                        "id": "default",
                        "enabled": True,
                        "token": "default",
                    },
                    {
                        "id": "product",
                        "enabled": True,
                        "token": "product",
                    },
                    {
                        "id": "off",
                        "enabled": False,
                        "token": "off",
                    },
                ]
            }
        }
    })

    manager = ChannelManager(cfg, MessageBus())

    assert set(manager.channels) == {"multi", "multi.product"}
    assert manager.channels["multi"].name == "multi"
    assert manager.channels["multi.product"].name == "multi.product"


def test_channel_manager_loads_descriptor_but_not_disabled_runtime(monkeypatch):
    load_calls: list[str] = []
    plugin = ChannelPlugin(
        name="fakeplugin",
        display_name="Fake Plugin",
        runtime="missing.fakeplugin.runtime:FakePlugin",
    )
    config = Config.model_validate({
        "channels": {
            "fakeplugin": {
                "enabled": False,
                "instances": [{"enabled": True}],
            }
        }
    })

    monkeypatch.setattr(
        "nanobot.channels.registry._channel_package_names",
        lambda: ["fakeplugin"],
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.load_channel_package",
        lambda _name: load_calls.append("descriptor") or plugin,
    )

    manager = ChannelManager(config, MessageBus())

    assert manager.channels == {}
    assert load_calls == ["descriptor"]


def test_feature_payload_uses_unified_instance_activation(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "multi": {
                "enabled": False,
                "instances": [{"id": "default", "enabled": True}],
            }
        }
    })
    _stub_channel_registry(monkeypatch, _channel_plugin(_FakeMultiChannel))
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    assert payload["features"][0]["enabled"] is True
    assert payload["features"][0]["ready"] is True
    assert payload["features"][0]["status"] == "enabled"
    assert payload["enabled_count"] == 1


def test_multi_plugin_action_defaults_to_default_instance(
    monkeypatch,
    tmp_path,
):
    from nanobot.config import loader
    from nanobot.webui.nanobot_features_api import nanobot_features_action

    class _ManagedMultiPlugin(_FakeMultiChannel):
        name = "managedmulti"

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "channels": {
                "managedmulti": {
                    "enabled": True,
                    "instances": [
                        {"id": "default", "enabled": True, "token": "default"},
                        {"id": "product", "enabled": True, "token": "product"},
                    ],
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_registry(
        monkeypatch,
        _channel_plugin(_ManagedMultiPlugin, management=_fake_multi_management()),
    )
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    disabled = nanobot_features_action("disable", {"name": ["managedmulti"]})
    saved = json.loads(config_path.read_text(encoding="utf-8"))["channels"]["managedmulti"]
    assert saved["enabled"] is True
    assert [item["enabled"] for item in saved["instances"]] == [False, True]
    assert disabled["features"][0]["enabled"] is True

    enabled = nanobot_features_action("enable", {"name": ["managedmulti"]})
    saved = json.loads(config_path.read_text(encoding="utf-8"))["channels"]["managedmulti"]
    assert saved["enabled"] is True
    assert [item["enabled"] for item in saved["instances"]] == [True, True]
    assert enabled["features"][0]["enabled"] is True

    explicit = nanobot_features_action(
        "disable",
        {"name": ["managedmulti"], "instance_id": ["default"]},
    )
    saved = json.loads(config_path.read_text(encoding="utf-8"))["channels"]["managedmulti"]
    assert saved["enabled"] is True
    assert [item["enabled"] for item in saved["instances"]] == [False, True]
    assert explicit["features"][0]["enabled"] is True


async def test_single_channel_enable_applies_defaults_before_hot_reload(
    monkeypatch,
    tmp_path,
):
    from nanobot.config import loader
    from nanobot.webui.nanobot_features_api import nanobot_features_action

    class _SingleDefaultsPlugin(_FakePlugin):
        name = "singleplugin"

        @classmethod
        def default_config(cls):
            return {
                "enabled": False,
                "endpoint": "https://plugin.example/api",
                "retries": 3,
            }

        def __init__(self, config, bus):
            super().__init__(config, bus)
            self.endpoint = config["endpoint"]
            self.retries = config["retries"]

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"singleplugin": {"enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_registry(monkeypatch, _channel_plugin(_SingleDefaultsPlugin))
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    manager = ChannelManager(
        Config.model_validate({"channels": {"singleplugin": {"enabled": False}}}),
        MessageBus(),
    )

    payload = nanobot_features_action("enable", {"name": ["singleplugin"]})
    hot_reload = await manager.apply_channel_feature_action("enable", "singleplugin")

    saved = json.loads(config_path.read_text(encoding="utf-8"))["channels"]["singleplugin"]
    assert saved == {
        "enabled": True,
        "endpoint": "https://plugin.example/api",
        "retries": 3,
    }
    assert payload["features"][0]["enabled"] is True
    assert hot_reload["ok"] is True
    assert hot_reload["requires_restart"] is False
    assert set(manager.channels) == {"singleplugin"}
    assert manager.channels["singleplugin"].endpoint == "https://plugin.example/api"
    assert manager.channels["singleplugin"].retries == 3


def test_channel_manager_preserves_single_instance_plugin_owned_instances(monkeypatch):
    _stub_channel_registry(monkeypatch, _channel_plugin(_FakePlugin))
    config = Config.model_validate({
        "channels": {
            "fakeplugin": {
                "enabled": True,
                "instances": ["plugin-owned-value"],
            }
        }
    })

    manager = ChannelManager(config, MessageBus())

    assert set(manager.channels) == {"fakeplugin"}
    assert manager.channels["fakeplugin"].config["instances"] == ["plugin-owned-value"]


# ---------------------------------------------------------------------------
# Channel package discovery
# ---------------------------------------------------------------------------

def test_discover_plugins_loads_package_descriptors():
    from nanobot.channels.registry import discover_plugins

    plugin = _channel_plugin(_FakeLine)
    with (
        patch("nanobot.channels.registry._channel_package_names", return_value=["line"]),
        patch("nanobot.channels.registry.load_channel_package", return_value=plugin),
    ):
        result = discover_plugins()

    assert "line" in result
    assert isinstance(result["line"], ChannelPlugin)


def test_plugin_setup_contract_drives_feature_payload(monkeypatch: pytest.MonkeyPatch):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "setupplugin": {
                "enabled": False,
                "token": "plugin-secret",
                "region": "eu",
            }
        }
    })
    _stub_channel_registry(
        monkeypatch,
        _channel_plugin(_SetupPlugin, setup=_SETUP_PLUGIN_SPEC),
    )
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    feature = payload["features"][0]
    assert feature["configured"] is True
    assert feature["setup"] == {
        "fields": [
            {
                "key": "channels.setupplugin.token",
                "field": "token",
                "kind": "secret",
                "choices": [],
                "required": True,
            },
            {
                "key": "channels.setupplugin.region",
                "field": "region",
                "kind": "enum",
                "choices": ["eu", "us"],
                "required": False,
            },
        ],
        "official_url": "https://plugin.example/setup",
    }
    assert feature["configured_fields"] == [
        "channels.setupplugin.token",
        "channels.setupplugin.region",
    ]
    assert feature["config_values"] == {"channels.setupplugin.region": "eu"}


def test_plugin_contract_error_is_isolated_in_feature_payload(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    class _BrokenPlugin(_FakePlugin):
        name = "broken"
        display_name = "Broken"

    def broken_instance_specs(section, *, enabled_only=True):
        raise ValueError("malformed plugin instance config")

    config = Config.model_validate({
        "channels": {
            "broken": {"enabled": True},
            "setupplugin": {"enabled": False, "token": "plugin-secret"},
        }
    })
    _stub_channel_registry(
        monkeypatch,
        _channel_plugin(
            _BrokenPlugin,
            management=ChannelManagementSpec(
                multi_instance=True,
                instance_specs=broken_instance_specs,
                update_instance_config=lambda section, values, *, instance_id="default": values,
            ),
        ),
        _channel_plugin(_SetupPlugin, setup=_SETUP_PLUGIN_SPEC),
    )
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    features = {feature["name"]: feature for feature in payload["features"]}
    assert features["broken"] == {
        "name": "broken",
        "display_name": "Broken",
        "type": "channel",
        "capabilities": [],
        "settings_visible": True,
        "setup": {"fields": []},
        "enabled": False,
        "configured": False,
        "installed": True,
        "ready": False,
        "status": "invalid_config",
        "install_supported": True,
        "requires_restart": True,
        "error": "Channel configuration could not be inspected.",
    }
    assert features["setupplugin"]["configured"] is True


def test_plugin_setup_contract_drives_save_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from nanobot.channels.validation import validate_channel_config
    from nanobot.config import loader
    from nanobot.webui.settings_routes import WebUISettingsRouter

    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_registry(
        monkeypatch,
        _channel_plugin(_SetupPlugin, setup=_SETUP_PLUGIN_SPEC),
    )
    router = object.__new__(WebUISettingsRouter)

    saved = router._save_channel_config_values(
        "setupplugin",
        {
            "channels.setupplugin.token": "plugin-secret",
            "channels.setupplugin.region": "eu",
        },
    )
    validation = validate_channel_config("setupplugin")

    assert saved == [
        "channels.setupplugin.token",
        "channels.setupplugin.region",
    ]
    assert load_config(config_path).channels.setupplugin["token"] == "plugin-secret"
    assert validation["status"] == "connected"
    assert validation["checks"][0]["id"] == "plugin"


def test_generic_plugin_validation_enforces_composite_requirements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nanobot.channels.validation import validate_channel_config
    from nanobot.config import loader

    class _CompositeSetupPlugin(_FakePlugin):
        name = "compositeplugin"

    setup_spec = ChannelSetupSpec(
        fields={
            "password": ChannelFieldSpec(kind="secret"),
            "accessToken": ChannelFieldSpec(kind="secret"),
            "deviceId": ChannelFieldSpec(),
        },
        required=(
            SetupRequirement.one_of(
                ("password",),
                ("accessToken", "deviceId"),
            ),
        ),
    )

    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_registry(
        monkeypatch,
        _channel_plugin(_CompositeSetupPlugin, setup=setup_spec),
    )

    missing = validate_channel_config("compositeplugin")
    partial = validate_channel_config(
        "compositeplugin",
        {"channels.compositeplugin.accessToken": "token"},
    )
    complete = validate_channel_config(
        "compositeplugin",
        {
            "channels.compositeplugin.accessToken": "token",
            "channels.compositeplugin.deviceId": "DEVICE",
        },
    )

    assert missing["status"] == "needs_setup"
    assert missing["can_enable"] is False
    assert "password" in missing["missing_fields"]
    assert partial["status"] == "needs_setup"
    assert partial["can_enable"] is False
    assert "deviceId" in partial["missing_fields"]
    assert complete["status"] == "configured"
    assert complete["can_enable"] is True


def test_webui_save_rejects_duplicate_feishu_ids_without_writing(monkeypatch, tmp_path):
    from nanobot.config import loader
    from nanobot.webui.settings_api import WebUISettingsError
    from nanobot.webui.settings_routes import WebUISettingsRouter

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "channels": {
                "feishu": {
                    "instances": [
                        {"id": "default", "enabled": True, "appId": "A"},
                        {"id": "default", "enabled": False, "appId": "B"},
                    ]
                }
            }
        }),
        encoding="utf-8",
    )
    before = config_path.read_text(encoding="utf-8")
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    router = object.__new__(WebUISettingsRouter)

    with pytest.raises(WebUISettingsError, match="duplicate Feishu instance id 'default'") as error:
        router._save_channel_config_values(
            "feishu",
            {"channels.feishu.appId": "updated"},
        )

    assert error.value.status == 400
    assert config_path.read_text(encoding="utf-8") == before


def test_discover_plugins_skips_names_outside_enabled_set():
    from nanobot.channels.registry import discover_plugins

    loaded: list[str] = []

    def _load_disabled(_name: str):
        loaded.append("disabled")
        return _channel_plugin(_FakePlugin)

    with (
        patch("nanobot.channels.registry._channel_package_names", return_value=["disabled"]),
        patch("nanobot.channels.registry.load_channel_package", side_effect=_load_disabled),
    ):
        result = discover_plugins({"enabled"})

    assert result == {}
    assert loaded == []


def test_discover_plugins_warns_once_for_legacy_entry_points():
    from nanobot.channels.registry import _warn_legacy_channel_entry_points, discover_plugins

    legacy_entry_points = [SimpleNamespace(name="z-old"), SimpleNamespace(name="a-old")]
    _warn_legacy_channel_entry_points.cache_clear()
    try:
        with (
            patch(
                "nanobot.channels.registry.entry_points",
                return_value=legacy_entry_points,
            ) as metadata_entry_points,
            patch("nanobot.channels.registry._channel_package_names", return_value=[]),
            patch("nanobot.channels.registry.logger.warning") as warning,
        ):
            discover_plugins()
            discover_plugins()
    finally:
        _warn_legacy_channel_entry_points.cache_clear()

    metadata_entry_points.assert_called_once_with(group="nanobot.channels")
    warning.assert_called_once_with(
        "Legacy channel entry points were detected but will not be loaded: {}. "
        "The '{}' entry-point group is no longer supported; use a built-in channel or "
        "migrate it into nanobot/channels/<channel>/.",
        "a-old, z-old",
        "nanobot.channels",
    )


def test_channel_manifest_rejects_invalid_dependency_metadata():
    with pytest.raises(TypeError, match="tuple of requirements"):
        ChannelPlugin(
            name="broken",
            display_name="Broken",
            runtime="broken.runtime:BrokenChannel",
            dependencies=["broken-sdk>=1"],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="valid requirement"):
        ChannelPlugin(
            name="broken",
            display_name="Broken",
            runtime="broken.runtime:BrokenChannel",
            dependencies=("not a requirement ???",),
        )


def test_discover_plugins_handles_load_error():
    from nanobot.channels.registry import discover_plugins

    def _boom(_name: str):
        raise RuntimeError("broken")

    with (
        patch("nanobot.channels.registry._channel_package_names", return_value=["broken"]),
        patch("nanobot.channels.registry.load_channel_package", side_effect=_boom),
    ):
        result = discover_plugins()

    assert "broken" not in result


# ---------------------------------------------------------------------------
# Runtime discovery
# ---------------------------------------------------------------------------

def test_discover_all_includes_available_channel_packages():
    from nanobot.channels.registry import discover_all, discover_plugins

    result = discover_all()

    # discover_all() only returns channels that are actually available (dependencies installed)
    # discover_plugins() returns all channel package descriptors
    # So we check that all actually loaded channels are in the result
    for name in result:
        assert name in discover_plugins()


def test_discover_plugins_excludes_internal_helpers():
    from nanobot.channels.registry import discover_plugins

    names = discover_plugins()

    assert "_feishu_ws" not in names
    assert "_setup" not in names
    assert "setup" not in names
    assert "_feishu_instances" not in names


def test_discover_enabled_imports_only_enabled_packages():
    from nanobot.channels.registry import discover_enabled

    class _EnabledPlugin(_FakePlugin):
        name = "enabled"

    plugins = {
        "enabled": _channel_plugin(_EnabledPlugin),
        "disabled": ChannelPlugin(
            name="disabled",
            display_name="Disabled",
            runtime="missing.disabled.runtime:DisabledPlugin",
        ),
    }

    result = discover_enabled({"enabled"}, _plugins=plugins)

    assert result == {"enabled": _EnabledPlugin}


def test_discover_enabled_warns_for_enabled_package_import_errors():
    from nanobot.channels.registry import discover_enabled

    plugin = ChannelPlugin(
        name="matrix",
        display_name="Matrix",
        runtime="missing.matrix.runtime:MatrixChannel",
    )
    with patch("nanobot.channels.registry.logger.warning") as warning:
        result = discover_enabled(
            {"matrix"},
            _plugins={"matrix": plugin},
            warn_import_errors=True,
        )

    assert result == {}
    warning.assert_called_once()
    assert warning.call_args.args[0] == "Enabled channel '{}' runtime is not available: {}"
    assert warning.call_args.args[1] == "matrix"
    assert "missing" in str(warning.call_args.args[2])


# ---------------------------------------------------------------------------
# Manager _init_channels with dict config
# ---------------------------------------------------------------------------

def test_manager_loads_plugin_from_dict_config(monkeypatch):
    """ChannelManager should instantiate a channel package from a raw dict config."""
    from nanobot.channels.manager import ChannelManager

    fake_config = Config.model_validate({
        "channels": {
            "fakeplugin": {"enabled": True, "allowFrom": ["*"]},
        }
    })
    _stub_channel_registry(monkeypatch, _channel_plugin(_FakePlugin))

    mgr = ChannelManager(fake_config, MessageBus())

    assert "fakeplugin" in mgr.channels
    assert isinstance(mgr.channels["fakeplugin"], _FakePlugin)


def test_manager_installs_manifest_dependencies_before_loading_enabled_channel(monkeypatch):
    from nanobot.optional_features import InstallResult

    plugin = _channel_plugin(
        _FakePlugin,
        dependencies=("fake-sdk>=1",),
    )
    _stub_channel_registry(monkeypatch, plugin)
    installed = False
    installs: list[tuple[str, list[str]]] = []

    def extra_installed(_name: str, _dependencies: list[str] | None) -> bool:
        return installed

    def install_extra(name: str, dependencies: list[str], *, runner):
        nonlocal installed
        installs.append((name, dependencies))
        installed = True
        return InstallResult(True, name, ["pip"])

    monkeypatch.setattr("nanobot.optional_features.extra_installed", extra_installed)
    monkeypatch.setattr("nanobot.optional_features.install_extra", install_extra)
    config = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "fakeplugin": {"enabled": True},
        }
    })

    manager = ChannelManager(config, MessageBus())

    assert installs == [("fakeplugin", ["fake-sdk>=1"])]
    assert "fakeplugin" in manager.channels


def test_manager_reports_dependency_install_failure_as_runtime_failure(monkeypatch):
    from nanobot.optional_features import InstallResult

    plugin = _channel_plugin(
        _FakePlugin,
        dependencies=("fake-sdk>=1",),
    )
    _stub_channel_registry(monkeypatch, plugin)
    monkeypatch.setattr(
        "nanobot.optional_features.extra_installed",
        lambda _name, _dependencies: False,
    )
    monkeypatch.setattr(
        "nanobot.optional_features.install_extra",
        lambda name, _dependencies, *, runner: InstallResult(False, name, ["pip"]),
    )
    config = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "fakeplugin": {"enabled": True},
        }
    })

    manager = ChannelManager(config, MessageBus())

    assert manager.channels == {}
    assert manager.get_status()["fakeplugin"] == {
        "enabled": True,
        "running": False,
        "state": "failed",
        "owner": "fakeplugin",
        "instance_id": "default",
        "error": "Channel dependencies could not be installed. Check gateway logs.",
    }


def test_manager_loads_websocket_from_default_config():
    from nanobot.channels.manager import ChannelManager

    class _FakeWebSocket(_FakePlugin):
        name = "websocket"
        display_name = "WebSocket"

        def __init__(self, config, bus, *, gateway):
            super().__init__(config, bus)
            self.gateway = gateway

        @classmethod
        def default_config(cls):
            return {"enabled": True, "host": "127.0.0.1"}

    plugin = _channel_plugin(_FakeWebSocket, default_enabled=True)
    with patch("nanobot.channels.registry.discover_plugins", return_value={"websocket": plugin}):
        mgr = ChannelManager(Config(), MessageBus(), webui_static_dist=False)

    assert "websocket" in mgr.channels
    assert mgr.channels["websocket"].config["enabled"] is True
    assert mgr.channels["websocket"].config["host"] == "127.0.0.1"


def test_manager_respects_explicitly_disabled_websocket_config():
    from nanobot.channels.manager import ChannelManager

    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    plugin = ChannelPlugin(
        name="websocket",
        display_name="WebSocket",
        runtime="missing.websocket.runtime:WebSocketChannel",
        default_enabled=True,
    )
    with patch("nanobot.channels.registry.discover_plugins", return_value={"websocket": plugin}):
        mgr = ChannelManager(config, MessageBus(), webui_static_dist=False)

    assert "websocket" not in mgr.channels


@pytest.mark.asyncio
async def test_base_channel_reads_current_transcription_config_each_call(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """BaseChannel.transcribe_audio resolves config at call time, not manager init time."""
    from nanobot.providers import transcription as transcription_mod

    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.provider = "openai"
    config.transcription.model = "whisper-custom"
    config.transcription.language = "en"
    config.providers.openai.api_key = "openai-key"
    config.providers.openai.api_base = "http://openai.local/v1/audio/transcriptions"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    channel = _FakePlugin({"enabled": True, "allowFrom": ["*"]}, MessageBus())

    calls: list[dict[str, object]] = []

    class _StubOpenAI:
        def __init__(self, api_key=None, api_base=None, language=None, model=None):
            calls.append({
                "provider": "openai",
                "api_key": api_key,
                "api_base": api_base,
                "language": language,
                "model": model,
            })

        async def transcribe(self, file_path):
            return "openai-ok"

    class _StubGroq:
        def __init__(self, api_key=None, api_base=None, language=None, model=None):
            calls.append({
                "provider": "groq",
                "api_key": api_key,
                "api_base": api_base,
                "language": language,
                "model": model,
            })

        async def transcribe(self, file_path):
            return "groq-ok"

    with (
        patch.object(transcription_mod, "OpenAITranscriptionProvider", _StubOpenAI),
        patch.object(transcription_mod, "GroqTranscriptionProvider", _StubGroq),
    ):
        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == "openai-ok"

        config.transcription.provider = "groq"
        config.transcription.model = "whisper-large-v3-turbo"
        config.transcription.language = "ko"
        config.providers.groq.api_key = "groq-key"
        config.providers.groq.api_base = "http://groq.local/v1/audio/transcriptions"
        save_config(config, config_path)

        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == "groq-ok"

    assert calls == [
        {
            "provider": "openai",
            "api_key": "openai-key",
            "api_base": "http://openai.local/v1/audio/transcriptions",
            "language": "en",
            "model": "whisper-custom",
        },
        {
            "provider": "groq",
            "api_key": "groq-key",
            "api_base": "http://groq.local/v1/audio/transcriptions",
            "language": "ko",
            "model": "whisper-large-v3-turbo",
        },
    ]


@pytest.mark.asyncio
async def test_base_channel_respects_disabled_transcription_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    config = Config()
    config.transcription.enabled = False
    config.providers.groq.api_key = "groq-key"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    channel = _FakePlugin({"enabled": True, "allowFrom": ["*"]}, MessageBus())

    with patch("nanobot.providers.transcription.GroqTranscriptionProvider") as provider:
        assert await channel.transcribe_audio("/tmp/does-not-matter.wav") == ""
    provider.assert_not_called()


def test_openai_transcription_provider_honors_api_base_argument():
    from nanobot.providers.transcription import OpenAITranscriptionProvider

    default = OpenAITranscriptionProvider(api_key="k")
    assert default.api_url == "https://api.openai.com/v1/audio/transcriptions"

    custom = OpenAITranscriptionProvider(
        api_key="k", api_base="http://override/v1/audio/transcriptions"
    )
    assert custom.api_url == "http://override/v1/audio/transcriptions"


# ---------------------------------------------------------------------------
# Transcription provider HTTP tests
# ---------------------------------------------------------------------------


class _StubResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "hello"}


def _stub_async_client(captured: dict[str, object]):
    """Return an httpx.AsyncClient stub that records POST calls into *captured*."""
    class _AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, files=None, timeout=None):
            captured["files"] = files
            return _StubResponse()

    return _AsyncClient()


@pytest.mark.parametrize(
    "provider_cls,language",
    [(_GroqProvider, "ko"), (_OpenAIProvider, "en")],
    ids=["groq", "openai"],
)
@pytest.mark.asyncio
async def test_transcription_provider_includes_language(tmp_path, provider_cls, language):
    """Provider must include the 'language' field in multipart body when set."""
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=_stub_async_client(captured)):
        provider = provider_cls(api_key="k", language=language)
        result = await provider.transcribe(audio)

    assert result == "hello"
    assert captured["files"]["language"] == (None, language)


@pytest.mark.parametrize(
    "provider_cls",
    [_GroqProvider, _OpenAIProvider],
    ids=["groq", "openai"],
)
@pytest.mark.asyncio
async def test_transcription_provider_omits_language_when_none(tmp_path, provider_cls):
    """When language is not set, the 'language' key must be absent from the multipart body."""
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    captured: dict[str, object] = {}

    with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=_stub_async_client(captured)):
        provider = provider_cls(api_key="k")
        result = await provider.transcribe(audio)

    assert result == "hello"
    assert "language" not in captured["files"]


def test_channels_login_uses_discovered_plugin_class(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}

    class _LoginPlugin(_FakePlugin):
        display_name = "Login Plugin"

        async def login(self, force: bool = False) -> bool:
            seen["force"] = force
            seen["config"] = self.config
            return True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {"fakeplugin": _LoginPlugin},
    )

    result = runner.invoke(app, ["channels", "login", "fakeplugin", "--force"])

    assert result.exit_code == 0
    assert seen["force"] is True


def test_channels_login_sets_custom_config_path(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}
    config_path = tmp_path / "custom-config.json"

    class _LoginPlugin(_FakePlugin):
        async def login(self, force: bool = False) -> bool:
            return True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {"fakeplugin": _LoginPlugin},
    )

    result = runner.invoke(app, ["channels", "login", "fakeplugin", "--config", str(config_path)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_path.resolve()


def test_channels_status_sets_custom_config_path(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    seen: dict[str, object] = {}
    config_path = tmp_path / "custom-config.json"

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: Config())
    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(app, ["channels", "status", "--config", str(config_path)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_path.resolve()


def test_plugins_list_shows_available_features(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    from nanobot.config.schema import Config

    runner = CliRunner()
    config = Config.model_validate({"channels": {"weixin": {"enabled": True}}})
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: config)
    _stub_channel_packages(monkeypatch, "weixin")
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"weixin": ["qrcode[pil]>=8.0"], "bedrock": ["boto3>=1.43.0"]},
    )

    result = runner.invoke(app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "Available Features" in result.stdout
    assert "weixin" in result.stdout
    assert "bedrock" in result.stdout
    assert "channel" in result.stdout
    assert "feature" in result.stdout
    assert " - " not in result.stdout


def test_plugins_list_reads_multi_instance_state_without_runtime(monkeypatch):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    plugin = ChannelPlugin(
        name="managedmulti",
        display_name="Managed multi",
        runtime="missing.managedmulti.runtime:ManagedMultiChannel",
        setup=ChannelSetupSpec(fields={}),
        management=_fake_multi_management(),
    )
    config = Config.model_validate({
        "channels": {
            "managedmulti": {
                "instances": [{"id": "default", "enabled": True}],
            }
        }
    })
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda config_path=None: config)
    _stub_channel_registry(monkeypatch, plugin)
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    result = CliRunner().invoke(app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "managedmulti" in result.stdout
    assert "yes" in result.stdout


def test_plugins_enable_channel_installs_extra_and_writes_config(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    class _WeixinChannel(_FakePlugin):
        name = "weixin"
        display_name = "Weixin"

        @classmethod
        def default_config(cls):
            return {"enabled": False, "token": "", "allowFrom": []}

    commands: list[list[str]] = []
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"weixin": {"enabled": False, "token": "keep"}}}),
        encoding="utf-8",
    )

    runner = CliRunner()
    _stub_optional_feature_cli(
        monkeypatch,
        extras={"weixin": ["qrcode[pil]>=8.0", "pycryptodome>=3.20.0"]},
        installed=False,
        commands=commands,
        channels=["weixin"],
        channel_cls=_WeixinChannel,
    )

    result = runner.invoke(app, ["plugins", "enable", "weixin", "--config", str(config_path)])

    assert result.exit_code == 0
    assert commands == [
        [sys.executable, "-m", "pip", "install", "qrcode[pil]>=8.0", "pycryptodome>=3.20.0"]
    ]
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["weixin"]["enabled"] is True
    assert data["channels"]["weixin"]["token"] == "keep"
    assert data["channels"]["weixin"]["allowFrom"] == []


def test_plugins_enable_extra_without_channel_only_installs(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli import commands as cli_commands
    from nanobot.cli.commands import app

    commands: list[list[str]] = []
    log_flags: list[bool] = []
    config_path = tmp_path / "config.json"
    original_set_logs = cli_commands._set_nanobot_logs

    def _set_logs(enabled: bool) -> None:
        log_flags.append(enabled)
        original_set_logs(enabled)

    runner = CliRunner()
    _stub_optional_feature_cli(
        monkeypatch,
        extras={"bedrock": ["boto3>=1.43.0"]},
        installed=False,
        commands=commands,
    )
    monkeypatch.setattr("nanobot.cli.commands._set_nanobot_logs", _set_logs)

    result = runner.invoke(app, ["plugins", "enable", "bedrock", "--config", str(config_path)])

    assert result.exit_code == 0
    assert log_flags == [False]
    assert commands == [[sys.executable, "-m", "pip", "install", "boto3>=1.43.0"]]
    assert "Installing optional feature" not in result.output
    assert not config_path.exists()


def test_plugins_enable_logs_option_enables_nanobot_logs(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli import commands as cli_commands
    from nanobot.cli.commands import app

    config_path = tmp_path / "config.json"
    log_flags: list[bool] = []
    original_set_logs = cli_commands._set_nanobot_logs

    def _set_logs(enabled: bool) -> None:
        log_flags.append(enabled)
        original_set_logs(enabled)

    runner = CliRunner()
    _stub_optional_feature_cli(
        monkeypatch,
        extras={"bedrock": ["boto3>=1.43.0"]},
        installed=False,
        commands=[],
    )
    monkeypatch.setattr("nanobot.cli.commands._set_nanobot_logs", _set_logs)

    result = runner.invoke(
        app,
        ["plugins", "enable", "bedrock", "--logs", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert log_flags == [True]
    assert "Enabled feature 'bedrock'" in result.output


def test_plugins_enable_skips_install_when_extra_is_present(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    commands: list[list[str]] = []
    config_path = tmp_path / "config.json"

    runner = CliRunner()
    _stub_optional_feature_cli(
        monkeypatch,
        extras={"bedrock": ["boto3>=1.43.0"]},
        installed=True,
        commands=commands,
    )

    result = runner.invoke(app, ["plugins", "enable", "bedrock", "--config", str(config_path)])

    assert result.exit_code == 0
    assert commands == []
    assert not config_path.exists()


def test_repository_dependency_installer_selects_all_channel_manifests(monkeypatch):
    from scripts import install_channel_dependencies as dependencies

    plugins = {
        "second": ChannelPlugin(
            name="second",
            display_name="Second",
            runtime="missing.second.runtime:SecondChannel",
            dependencies=("second-sdk>=2",),
        ),
        "first": ChannelPlugin(
            name="first",
            display_name="First",
            runtime="missing.first.runtime:FirstChannel",
            dependencies=("first-sdk>=1",),
        ),
    }
    prepared: list[tuple[set[str], dict[str, ChannelPlugin]]] = []
    monkeypatch.setattr(dependencies, "discover_plugins", lambda: plugins)
    monkeypatch.setattr(
        dependencies,
        "ensure_enabled_channel_dependencies",
        lambda names, discovered: prepared.append((names, discovered)) or {},
    )

    assert dependencies.main(["--all-channels"]) == 0
    assert prepared == [(set(plugins), plugins)]


def test_repository_dependency_installer_rejects_unknown_channel(monkeypatch, capsys):
    from scripts import install_channel_dependencies as dependencies

    monkeypatch.setattr(dependencies, "discover_plugins", lambda: {})

    assert dependencies.main(["missing"]) == 2
    assert "Unknown channels: missing" in capsys.readouterr().err


def test_repository_dependency_installer_propagates_install_failure(monkeypatch, capsys):
    from scripts import install_channel_dependencies as dependencies

    plugin = ChannelPlugin(
        name="demo",
        display_name="Demo",
        runtime="missing.demo.runtime:DemoChannel",
    )
    monkeypatch.setattr(dependencies, "discover_plugins", lambda: {"demo": plugin})
    monkeypatch.setattr(
        dependencies,
        "ensure_enabled_channel_dependencies",
        lambda _names, _plugins: {"demo": "dependency install failed"},
    )

    assert dependencies.main(["demo"]) == 1
    assert "demo: dependency install failed" in capsys.readouterr().err


def test_plugins_disable_channel_writes_config(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"matrix": {"enabled": True, "homeserver": "keep"}}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    _stub_channel_packages(monkeypatch, "matrix")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    result = runner.invoke(app, ["plugins", "disable", "matrix", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Disabled channel 'matrix'" in result.output
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["matrix"]["enabled"] is False
    assert data["channels"]["matrix"]["homeserver"] == "keep"


def test_plugins_disable_rejects_non_channel_and_allows_websocket(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    config_path = tmp_path / "config.json"
    runner = CliRunner()
    _stub_channel_packages(monkeypatch, "matrix", "websocket")
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )

    non_channel = runner.invoke(
        app,
        ["plugins", "disable", "bedrock", "--config", str(config_path)],
    )
    websocket = runner.invoke(
        app,
        ["plugins", "disable", "websocket", "--config", str(config_path)],
    )

    assert non_channel.exit_code == 1
    assert "Feature 'bedrock' cannot be disabled" in non_channel.output
    assert websocket.exit_code == 0
    assert "Disabled channel 'websocket'" in websocket.output
    assert json.loads(config_path.read_text(encoding="utf-8"))["channels"]["websocket"][
        "enabled"
    ] is False


def test_enable_optional_feature_blocks_install_when_disallowed(monkeypatch, tmp_path):
    from nanobot.optional_features import OptionalFeatureError, enable_optional_feature

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_registry(monkeypatch)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: False)

    with pytest.raises(OptionalFeatureError) as exc:
        enable_optional_feature("bedrock", config_path=config_path, allow_install=False)

    assert exc.value.status == 403
    assert "remote WebUI is disabled" in exc.value.message
    assert not config_path.exists()


def test_enable_optional_feature_skips_install_when_dependency_present(
    monkeypatch,
    tmp_path,
):
    from nanobot.optional_features import InstallResult, enable_optional_feature

    config_path = tmp_path / "config.json"
    install_calls: list[str] = []
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_registry(monkeypatch)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: True)

    def _install_extra(
        name: str,
        deps: list[str] | None,
        *,
        runner,
    ) -> InstallResult:
        install_calls.append(name)
        return InstallResult(True, f"{name} support", ["python", "-m", "pip", "install", name])

    monkeypatch.setattr("nanobot.optional_features.install_extra", _install_extra)

    payload = enable_optional_feature("bedrock", config_path=config_path, allow_install=False)

    assert install_calls == []
    assert payload["last_action"]["message"] == "Enabled feature 'bedrock'"
    assert payload["requires_restart"] is True
    assert not config_path.exists()


def test_enable_optional_feature_lazy_reader_does_not_require_restart(monkeypatch, tmp_path):
    from nanobot.optional_features import enable_optional_feature

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_registry(monkeypatch)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"documents": ["pypdf>=5.0.0,<6.0.0"]},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: True)

    payload = enable_optional_feature("documents", config_path=config_path)

    assert payload["requires_restart"] is False
    assert payload["last_action"]["message"] == "Feature 'documents' is included with nanobot"


def test_enable_optional_feature_reports_install_failure(monkeypatch, tmp_path):
    from nanobot.optional_features import (
        InstallResult,
        OptionalFeatureError,
        enable_optional_feature,
    )

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_registry(monkeypatch)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: False)
    monkeypatch.setattr(
        "nanobot.optional_features.install_extra",
        lambda _name, _deps, *, runner: InstallResult(
            False,
            "bedrock support",
            ["python", "-m", "pip", "install", "boto3>=1.43.0"],
            failed_cmd=["python", "-m", "pip", "install", "boto3>=1.43.0"],
            output="network unavailable",
        ),
    )

    with pytest.raises(OptionalFeatureError) as exc:
        enable_optional_feature("bedrock", config_path=config_path)

    assert exc.value.status == 500
    assert "Failed:" in exc.value.message
    assert "network unavailable" in exc.value.message
    assert not config_path.exists()


def test_disable_optional_feature_rejects_unknown_features_and_non_channels(
    monkeypatch,
    tmp_path,
):
    from nanobot.optional_features import OptionalFeatureError, disable_optional_feature

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_packages(monkeypatch, "matrix", "websocket")
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"bedrock": ["boto3>=1.43.0"]},
    )

    with pytest.raises(OptionalFeatureError) as unknown:
        disable_optional_feature("missing", config_path=config_path)
    assert unknown.value.status == 404
    assert "Unknown feature: missing" in unknown.value.message

    with pytest.raises(OptionalFeatureError) as non_channel:
        disable_optional_feature("bedrock", config_path=config_path)
    assert non_channel.value.status == 400
    assert non_channel.value.message == "Feature 'bedrock' cannot be disabled"

    assert not config_path.exists()


def test_disable_optional_feature_writes_channel_disabled(monkeypatch, tmp_path):
    from nanobot.optional_features import disable_optional_feature

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config_path.write_text(
        json.dumps({"channels": {"matrix": {"enabled": True, "homeserver": "keep"}}}),
        encoding="utf-8",
    )
    _stub_channel_packages(monkeypatch, "matrix", "websocket")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = disable_optional_feature("matrix", config_path=config_path)

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["matrix"]["enabled"] is False
    assert data["channels"]["matrix"]["homeserver"] == "keep"
    assert payload["last_action"]["message"] == "Disabled channel 'matrix'"
    assert payload["requires_restart"] is True

    payload = disable_optional_feature("websocket", config_path=config_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["websocket"]["enabled"] is False
    assert payload["last_action"]["message"] == "Disabled channel 'websocket'"


def test_disable_multi_instance_channel_without_importing_runtime(monkeypatch, tmp_path):
    from nanobot.optional_features import disable_optional_feature

    plugin = ChannelPlugin(
        name="managedmulti",
        display_name="Managed multi",
        runtime="missing.managedmulti.runtime:ManagedMultiChannel",
        setup=ChannelSetupSpec(fields={}),
        management=_fake_multi_management(),
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "channels": {
                "managedmulti": {
                    "instances": [
                        {"id": "default", "enabled": True},
                        {"id": "product", "enabled": True},
                    ]
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    _stub_channel_registry(monkeypatch, plugin)
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = disable_optional_feature(
        "managedmulti",
        config_path=config_path,
        instance_id="product",
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert [item["enabled"] for item in saved["channels"]["managedmulti"]["instances"]] == [
        True,
        False,
    ]
    feature = payload["features"][0]
    assert feature["enabled"] is True
    assert [item["enabled"] for item in feature["instances"]] == [True, False]


def test_feishu_enable_rejects_duplicate_instance_ids_without_writing(tmp_path):
    from nanobot.channels.registry import load_channel_plugin
    from nanobot.optional_features import OptionalFeatureError, set_channel_config_enabled

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "channels": {
                "feishu": {
                    "instances": [
                        {"id": "default", "enabled": False, "appId": "A"},
                        {"id": "default", "enabled": True, "appId": "B"},
                    ]
                }
            }
        }),
        encoding="utf-8",
    )
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(OptionalFeatureError, match="duplicate Feishu instance id 'default'"):
        set_channel_config_enabled(config_path, "feishu", load_channel_plugin("feishu"), True)

    assert config_path.read_text(encoding="utf-8") == before


def test_optional_features_payload_counts_enabled_channel_with_missing_dependency(
    monkeypatch,
):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({"channels": {"matrix": {"enabled": True}}})
    _stub_channel_packages(monkeypatch, "matrix")
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"matrix": ["matrix-nio>=0.25.2"]},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: False)

    payload = optional_features_payload(config=config)

    matrix = payload["features"][0]
    assert matrix["name"] == "matrix"
    assert matrix["enabled"] is True
    assert matrix["installed"] is False
    assert matrix["ready"] is False
    assert payload["enabled_count"] == 1


def test_live_runtime_status_overrides_enabled_configuration_for_webui():
    from nanobot.optional_features import with_channel_runtime_status

    payload = {
        "features": [{
            "name": "feishu",
            "type": "channel",
            "enabled": True,
            "ready": True,
            "status": "enabled",
            "instances": [{
                "id": "default",
                "enabled": True,
                "configured": True,
            }],
        }],
        "enabled_count": 1,
    }
    runtime_status = {
        "feishu": {
            "owner": "feishu",
            "instance_id": "default",
            "state": "failed",
            "running": False,
            "error": "Channel failed to start. Check gateway logs.",
        }
    }

    decorated = with_channel_runtime_status(payload, runtime_status)

    feature = decorated["features"][0]
    assert feature["enabled"] is True  # desired config remains visible to actions
    assert feature["running"] is False
    assert feature["ready"] is False
    assert feature["runtime_status"] == "failed"
    assert feature["runtime_error"] == "Channel failed to start. Check gateway logs."
    assert feature["instances"][0]["runtime_status"] == "failed"
    assert decorated["enabled_count"] == 0


def test_package_manifest_metadata_drives_optional_feature_payload(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    plugin = ChannelPlugin(
        name="demo",
        display_name="Demo Chat",
        runtime="demo.runtime:DemoChannel",
        dependencies=("demo-sdk>=1",),
        default_enabled=True,
        capabilities=frozenset({"custom_ui"}),
        webui="webui/entry.tsx",
    )
    config = Config.model_validate({"channels": {"demo": {"enabled": False}}})
    checked_extras: list[tuple[str, list[str] | None]] = []

    _stub_channel_registry(monkeypatch, plugin)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {},
    )

    def record_extra(extra: str, deps: list[str] | None) -> bool:
        checked_extras.append((extra, deps))
        return True

    monkeypatch.setattr("nanobot.optional_features.extra_installed", record_extra)

    payload = optional_features_payload(config=config)

    demo = next(feature for feature in payload["features"] if feature["name"] == "demo")
    assert checked_extras == [("demo", ["demo-sdk>=1"])]
    assert demo["display_name"] == "Demo Chat"
    assert demo["capabilities"] == ["custom_ui"]
    assert demo["webui"] == "webui/entry.tsx"


def test_optional_features_payload_reflects_saved_channel_config(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "discord": {
                "enabled": False,
                "token": "discord-secret-token",
                "allowChannels": ["123", "456"],
                "groupPolicy": "open",
            }
        }
    })
    _stub_channel_packages(monkeypatch, "discord")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    discord = payload["features"][0]
    assert discord["name"] == "discord"
    assert discord["enabled"] is False
    assert discord["configured"] is True
    assert discord["config_values"] == {
        "channels.discord.allowChannels": "123, 456",
        "channels.discord.groupPolicy": "open",
    }
    assert discord["configured_fields"] == [
        "channels.discord.token",
        "channels.discord.allowChannels",
        "channels.discord.groupPolicy",
    ]
    assert "discord-secret-token" not in json.dumps(payload)


def test_optional_features_payload_marks_enabled_channel_missing_credentials(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({"channels": {"discord": {"enabled": True}}})
    _stub_channel_packages(monkeypatch, "discord")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    discord = payload["features"][0]
    assert discord["enabled"] is True
    assert discord["configured"] is False
    assert "config_values" not in discord
    assert "configured_fields" not in discord


def test_optional_features_payload_detects_saved_weixin_login_state(tmp_path, monkeypatch):
    from nanobot.optional_features import optional_features_payload

    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(
        json.dumps({"token": "saved-weixin-token"}),
        encoding="utf-8",
    )
    config = Config.model_validate({
        "channels": {
            "weixin": {
                "enabled": True,
                "stateDir": str(state_dir),
            }
        }
    })
    _stub_channel_packages(monkeypatch, "weixin")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    weixin = payload["features"][0]
    assert weixin["enabled"] is True
    assert weixin["configured"] is True


def test_optional_features_payload_detects_legacy_default_weixin_state(tmp_path, monkeypatch):
    from nanobot.config import loader
    from nanobot.optional_features import optional_features_payload

    config_path = tmp_path / "config.json"
    loader.save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    state_dir = tmp_path / "weixin"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(
        json.dumps({"token": "legacy-weixin-token"}),
        encoding="utf-8",
    )
    _stub_channel_packages(monkeypatch, "weixin")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=Config())

    weixin = payload["features"][0]
    assert weixin["enabled"] is False
    assert weixin["configured"] is True


@pytest.mark.parametrize("device_id", ["", "DEVICE-ID"])
def test_optional_features_payload_requires_matrix_device_id_for_token_login(
    monkeypatch,
    device_id,
):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "matrix": {
                "enabled": False,
                "homeserver": "https://matrix.example",
                "userId": "@nanobot:matrix.example",
                "accessToken": "saved-token",
                "deviceId": device_id,
            }
        }
    })
    _stub_channel_packages(monkeypatch, "matrix")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    assert payload["features"][0]["configured"] is bool(device_id)


def test_optional_features_payload_marks_disabled_feishu_as_configured(monkeypatch):
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "feishu": {
                "enabled": False,
                "appId": "cli_test",
                "appSecret": "secret",
            }
        }
    })

    plugin = load_channel_package("feishu")
    assert plugin is not None
    _stub_channel_registry(
        monkeypatch,
        replace(plugin, runtime="missing.feishu.runtime:FeishuChannel"),
    )
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    feishu = payload["features"][0]
    assert feishu["name"] == "feishu"
    assert feishu["enabled"] is False
    assert feishu["configured"] is True
    assert feishu["ready"] is False
    assert feishu["setup"]["fields"][0]["key"] == "channels.feishu.appId"
    assert payload["enabled_count"] == 0


def test_optional_features_payload_lists_feishu_instances(monkeypatch):
    from nanobot.channels.plugin import load_channel_package
    from nanobot.optional_features import optional_features_payload

    config = Config.model_validate({
        "channels": {
            "feishu": {
                "instances": [
                    {
                        "id": "default",
                        "name": "nanobot",
                        "displayName": "Voraflare Bot",
                        "avatarUrl": "https://example.com/bot.png",
                        "enabled": True,
                        "appId": "cli_default",
                        "appSecret": "secret",
                    },
                    {
                        "id": "product",
                        "name": "Product bot",
                        "enabled": False,
                        "appId": "cli_product",
                        "appSecret": "secret",
                    },
                ]
            }
        }
    })
    plugin = load_channel_package("feishu")
    assert plugin is not None
    _stub_channel_registry(
        monkeypatch,
        replace(plugin, runtime="missing.feishu.runtime:FeishuChannel"),
    )
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})

    payload = optional_features_payload(config=config)

    feishu = payload["features"][0]
    assert feishu["name"] == "feishu"
    assert feishu["enabled"] is True
    assert feishu["configured"] is True
    assert payload["enabled_count"] == 1
    assert feishu["instances"] == [
        {
            "id": "default",
            "name": "nanobot",
            "display_name": "Voraflare Bot",
            "avatar_url": "https://example.com/bot.png",
            "enabled": True,
            "configured": True,
            "config_values": {
                "channels.feishu.appId": "cli_default",
                "channels.feishu.domain": "feishu",
                "channels.feishu.groupPolicy": "mention",
                "channels.feishu.topicIsolation": "true",
            },
            "configured_fields": [
                "channels.feishu.appId",
                "channels.feishu.appSecret",
                "channels.feishu.domain",
                "channels.feishu.groupPolicy",
                "channels.feishu.topicIsolation",
            ],
        },
        {
            "id": "product",
            "name": "Product bot",
            "display_name": "Product bot",
            "avatar_url": "",
            "enabled": False,
            "configured": True,
            "config_values": {
                "channels.feishu.appId": "cli_product",
                "channels.feishu.domain": "feishu",
                "channels.feishu.groupPolicy": "mention",
                "channels.feishu.topicIsolation": "true",
            },
            "configured_fields": [
                "channels.feishu.appId",
                "channels.feishu.appSecret",
                "channels.feishu.domain",
                "channels.feishu.groupPolicy",
                "channels.feishu.topicIsolation",
            ],
        },
    ]


def test_optional_features_payload_does_not_refresh_saved_feishu_identity(monkeypatch, tmp_path):
    from nanobot.channels.feishu import runtime as feishu_module
    from nanobot.config import loader
    from nanobot.optional_features import optional_features_payload

    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({
            "channels": {
                "feishu": {
                    "instances": [{
                        "id": "default",
                        "name": "nanobot",
                        "enabled": True,
                        "appId": "cli_default",
                        "appSecret": "secret",
                    }]
                }
            }
        }),
        config_path,
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_packages(monkeypatch, "feishu")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    monkeypatch.setattr(
        feishu_module,
        "fetch_feishu_app_identity",
        lambda *_args: pytest.fail("feature discovery must not call Feishu"),
    )
    before = config_path.read_text(encoding="utf-8")

    payload = optional_features_payload()

    instance = payload["features"][0]["instances"][0]
    assert instance["display_name"] == "nanobot"
    assert instance["avatar_url"] == ""
    assert config_path.read_text(encoding="utf-8") == before


def test_enable_optional_feature_refreshes_feishu_identity(
    monkeypatch,
    tmp_path,
):
    from nanobot.channels.feishu import runtime as feishu_module
    from nanobot.config import loader
    from nanobot.optional_features import enable_optional_feature

    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({
            "channels": {
                "feishu": {
                    "instances": [{
                        "id": "default",
                        "name": "nanobot",
                        "enabled": True,
                        "appId": "cli_default",
                        "appSecret": "secret",
                    }]
                }
            }
        }),
        config_path,
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_packages(monkeypatch, "feishu")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    monkeypatch.setattr(feishu_module, "FEISHU_AVAILABLE", True)
    monkeypatch.setattr(
        feishu_module,
        "fetch_feishu_app_identity",
        lambda *_args: {
            "displayName": "Xubin Ren的智能助手",
            "avatarUrl": "https://example.com/assistant.png",
            "identityFetchedAt": "2026-07-06T00:00:00Z",
        },
    )

    payload = enable_optional_feature("feishu", config_path=config_path)

    instance = payload["features"][0]["instances"][0]
    assert instance["display_name"] == "Xubin Ren的智能助手"
    assert instance["avatar_url"] == "https://example.com/assistant.png"

    data = json.loads(config_path.read_text(encoding="utf-8"))
    saved = data["channels"]["feishu"]["instances"][0]
    assert saved["displayName"] == "Xubin Ren的智能助手"
    assert saved["avatarUrl"] == "https://example.com/assistant.png"
    assert saved["identityFetchedAt"] == "2026-07-06T00:00:00Z"


def test_optional_features_payload_preserves_legacy_flat_feishu_config(monkeypatch, tmp_path):
    from nanobot.channels.feishu import runtime as feishu_module
    from nanobot.config import loader
    from nanobot.optional_features import optional_features_payload

    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({
            "channels": {
                "feishu": {
                    "enabled": True,
                    "appId": "cli_legacy",
                    "appSecret": "legacy-secret",
                    "groupPolicy": "mention",
                }
            }
        }),
        config_path,
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    _stub_channel_packages(monkeypatch, "feishu")
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    monkeypatch.setattr(
        feishu_module,
        "fetch_feishu_app_identity",
        lambda *_args: pytest.fail("feature discovery must not call Feishu"),
    )
    before = config_path.read_text(encoding="utf-8")

    payload = optional_features_payload()

    assert payload["features"][0]["instances"][0]["display_name"] == "nanobot"
    assert config_path.read_text(encoding="utf-8") == before
    saved = json.loads(config_path.read_text(encoding="utf-8"))["channels"]["feishu"]
    assert saved["appId"] == "cli_legacy"
    assert saved["appSecret"] == "legacy-secret"
    assert "displayName" not in saved
    assert "avatarUrl" not in saved
    assert "instances" not in saved


def test_enable_bootstraps_pip_with_ensurepip(monkeypatch):
    from nanobot import optional_features

    calls: list[list[str]] = []

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="No module named pip")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    assert optional_features.install_extra("bedrock", None, runner=_run).ok is True
    assert calls == [
        [sys.executable, "-m", "pip", "install", "nanobot-ai[bedrock]"],
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        [sys.executable, "-m", "pip", "install", "nanobot-ai[bedrock]"],
    ]


def test_install_extra_logs_command_and_output(monkeypatch):
    from nanobot import optional_features

    records: list[str] = []

    class _Logger:
        def info(self, message: str, *args: object) -> None:
            records.append(message.format(*args))

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="install ok", stderr="")

    monkeypatch.setattr(optional_features, "logger", _Logger())

    result = optional_features.install_extra("weixin", ["qrcode[pil]>=8.0"], runner=_run)

    assert result.ok is True
    assert any("Installing optional feature 'weixin':" in record for record in records)
    assert any("Optional feature 'weixin' install exited with code 0" in record for record in records)
    assert any("install ok" in record for record in records)


def test_run_install_command_returns_failure_on_timeout(monkeypatch):
    from nanobot import optional_features

    def _run(*args, **kwargs):
        raise subprocess.TimeoutExpired(["pip"], 300, output="partial", stderr=b"still running")

    monkeypatch.setattr(optional_features.subprocess, "run", _run)

    result = optional_features.run_install_command(["pip"])

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.stderr == "still running\nTimed out after 300s"


def test_optional_dependency_metadata_for_enable():
    from nanobot import optional_features
    from nanobot.channels.plugin import load_channel_package

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["optional-dependencies"]
    required = data["project"]["dependencies"]

    assert "boto3>=1.43.0" not in data["project"]["dependencies"]
    assert deps["bedrock"] == ["boto3>=1.43.0"]
    for dep_name in (
        "aiohttp",
        "dingtalk-stream",
        "lark-oapi",
        "msgpack",
        "python-telegram-bot",
        "python-socketio",
        "qq-botpy",
        "slack-sdk",
        "slackify-markdown",
    ):
        assert not any(dep.startswith(dep_name) for dep in required)
    for dependency in (
        "tzdata>=2025.2; sys_platform == 'win32'",
        "defusedxml>=0.7.1,<1.0.0",
        "pypdf>=5.0.0,<6.0.0",
        "python-docx>=1.1.0,<2.0.0",
        "openpyxl>=3.1.0,<4.0.0",
        "python-pptx>=1.0.0,<2.0.0",
    ):
        assert dependency in required
    assert deps["documents"] == [
        "defusedxml>=0.7.1,<1.0.0",
        "pypdf>=5.0.0,<6.0.0",
        "python-docx>=1.1.0,<2.0.0",
        "openpyxl>=3.1.0,<4.0.0",
        "python-pptx>=1.0.0,<2.0.0",
    ]
    assert deps["pdf"] == ["pypdf>=5.0.0,<6.0.0"]
    assert deps["langfuse"] == ["langfuse>=3.0.0,<4.0.0"]
    channel_names = {
        "dingtalk",
        "discord",
        "feishu",
        "matrix",
        "mochat",
        "msteams",
        "napcat",
        "qq",
        "slack",
        "telegram",
        "wecom",
        "weixin",
        "whatsapp",
    }
    assert channel_names.isdisjoint(deps)
    expected_channel_dependencies = {
        "dingtalk": ("dingtalk-stream>=0.24.0,<1.0.0",),
        "discord": ("discord.py>=2.5.2,<3.0.0",),
        "feishu": ("lark-oapi>=1.5.0,<2.0.0",),
        "matrix": (
            "matrix-nio[e2e]>=0.25.2; sys_platform != 'win32'",
            "matrix-nio>=0.25.2; sys_platform == 'win32'",
            "aiohttp>=3.9.0,<4.0.0",
            "mistune>=3.0.0,<4.0.0",
            "nh3>=0.2.17,<1.0.0",
        ),
        "mochat": (
            "python-socketio>=5.16.0,<6.0.0",
            "msgpack>=1.1.0,<2.0.0",
        ),
        "msteams": ("PyJWT>=2.0,<3.0", "cryptography>=41.0"),
        "napcat": ("aiohttp>=3.9.0,<4.0.0",),
        "qq": (
            "aiohttp>=3.9.0,<4.0.0",
            "qq-botpy>=1.2.0,<2.0.0",
        ),
        "slack": (
            "aiohttp>=3.9.0,<4.0.0",
            "slack-sdk>=3.39.0,<4.0.0",
            "slackify-markdown>=0.2.0,<1.0.0",
        ),
        "telegram": (
            "python-telegram-bot[socks,webhooks]>=22.6,<23.0",
            "socksio>=1.0.0,<2.0.0",
            "python-socks[asyncio]>=2.8.0,<3.0.0; sys_platform != 'win32'",
        ),
        "wecom": ("wecom-aibot-sdk-python>=0.1.5",),
        "weixin": ("qrcode[pil]>=8.0", "pycryptodome>=3.20.0"),
        "whatsapp": (
            "neonize>=0.3.18.post0,<0.4.0",
            "segno>=1.6.1,<2.0.0",
        ),
    }
    for name, expected in expected_channel_dependencies.items():
        plugin = load_channel_package(name)
        assert plugin is not None
        assert plugin.dependencies == expected

    visible = optional_features.optional_dependency_groups()
    assert "documents" not in visible
    assert "pdf" not in visible


def test_optional_dependency_groups_falls_back_to_package_metadata(monkeypatch):
    from nanobot import optional_features

    class _Metadata:
        def get_all(self, key: str):
            assert key == "Provides-Extra"
            return ["bedrock", "dev"]

    monkeypatch.setattr(optional_features, "load_pyproject", lambda _path: {})
    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _Metadata())
    monkeypatch.setattr(
        "importlib.metadata.requires",
        lambda _name: [
            "packaging>=24.0",
            "boto3>=1.43.0; extra == 'bedrock'",
            "pytest>=8.0; extra == 'dev'",
        ],
    )

    deps = optional_features.optional_dependency_groups()

    assert deps == {"bedrock": ["boto3>=1.43.0; extra == 'bedrock'"]}
    assert optional_features.install_args_for_extra("bedrock", deps["bedrock"]) == (
        ["boto3>=1.43.0"],
        "bedrock support",
    )


def test_load_pyproject_propagates_malformed_toml(tmp_path):
    from nanobot import optional_features

    path = tmp_path / "pyproject.toml"
    path.write_text("[project\nname = 'nanobot'", encoding="utf-8")

    with pytest.raises(tomllib.TOMLDecodeError):
        optional_features.load_pyproject(path)


def test_optional_dependency_metadata_propagates_malformed_requirement(monkeypatch):
    from packaging.requirements import InvalidRequirement

    from nanobot import optional_features

    class _Metadata:
        def get_all(self, key: str):
            assert key == "Provides-Extra"
            return ["bedrock"]

    monkeypatch.setattr("importlib.metadata.metadata", lambda _name: _Metadata())
    monkeypatch.setattr(
        "importlib.metadata.requires",
        lambda _name: ["not a valid requirement ???"],
    )

    with pytest.raises(InvalidRequirement):
        optional_features.optional_dependency_groups_from_metadata()


def test_install_args_for_extra_resolves_metadata_markers_for_current_platform():
    from nanobot import optional_features

    current_platform = sys.platform
    deps = [
        f"current-platform-package>=1.0; sys_platform == '{current_platform}' and extra == 'matrix'",
        "other-platform-package>=1.0; sys_platform == 'never' and extra == 'matrix'",
    ]

    assert optional_features.install_args_for_extra("matrix", deps) == (
        ["current-platform-package>=1.0"],
        "matrix support",
    )


def test_requirement_installed_validates_requested_extras(monkeypatch):
    from nanobot import optional_features

    class _Metadata:
        def __init__(self, extras: list[str] | None = None) -> None:
            self._extras = extras or []

        def get_all(self, key: str):
            assert key == "Provides-Extra"
            return self._extras

    class _Distribution:
        def __init__(
            self,
            version: str,
            *,
            requires: list[str] | None = None,
            extras: list[str] | None = None,
        ) -> None:
            self.version = version
            self.requires = requires or []
            self.metadata = _Metadata(extras)

    installed: dict[str, _Distribution] = {
        "qrcode": _Distribution(
            "8.2",
            requires=["pillow>=9.1; extra == 'pil'"],
            extras=["pil"],
        ),
    }

    def _distribution(name: str) -> _Distribution:
        normalized = name.lower()
        if normalized not in installed:
            raise PackageNotFoundError(name)
        return installed[normalized]

    monkeypatch.setattr(optional_features, "distribution", _distribution)

    assert optional_features.requirement_installed("qrcode>=8.0") is True
    assert optional_features.requirement_installed("qrcode[pil]>=8.0") is False

    installed["pillow"] = _Distribution("10.0")

    assert optional_features.requirement_installed("qrcode[pil]>=8.0") is True


@pytest.mark.asyncio
async def test_manager_skips_disabled_channel_package(monkeypatch):
    fake_config = SimpleNamespace(
        channels=ChannelsConfig.model_validate({
            "fakeplugin": {"enabled": False},
        }),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    _stub_channel_registry(monkeypatch, _channel_plugin(_FakePlugin))
    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None
    mgr._init_channels()

    assert "fakeplugin" not in mgr.channels


# ---------------------------------------------------------------------------
# Channel default_config() and dict-to-Pydantic conversion
# ---------------------------------------------------------------------------

def test_channel_default_config():
    """Channels expose default_config() returning a dict with 'enabled': False."""
    from nanobot.channels.dingtalk.runtime import DingTalkChannel
    cfg = DingTalkChannel.default_config()
    assert isinstance(cfg, dict)
    assert cfg["enabled"] is False
    assert "clientId" in cfg


def test_channel_init_from_dict():
    """Channels accept a raw dict and convert to Pydantic internally."""
    from nanobot.channels.dingtalk.runtime import DingTalkChannel
    bus = MessageBus()
    ch = DingTalkChannel({"enabled": False, "clientId": "test-id", "allowFrom": ["*"]}, bus)
    assert ch.config.client_id == "test-id"
    assert ch.config.allow_from == ["*"]


def test_channels_config_send_max_retries_default():
    """ChannelsConfig should have send_max_retries with default value of 3."""
    cfg = ChannelsConfig()
    assert hasattr(cfg, 'send_max_retries')
    assert cfg.send_max_retries == 3


def test_channels_config_send_max_retries_upper_bound():
    """send_max_retries should be bounded to prevent resource exhaustion."""
    from pydantic import ValidationError

    # Value too high should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=100)

    # Negative should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=-1)

    # Boundary values should be allowed
    cfg_min = ChannelsConfig(send_max_retries=0)
    assert cfg_min.send_max_retries == 0

    cfg_max = ChannelsConfig(send_max_retries=10)
    assert cfg_max.send_max_retries == 10

    # Value above upper bound should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=11)


def test_channels_config_transcription_language_pattern():
    """transcription_language must match ISO-639 format (2-3 lowercase letters) or be None."""
    from pydantic import ValidationError

    # Valid values
    assert ChannelsConfig(transcription_language="en").transcription_language == "en"
    assert ChannelsConfig(transcription_language="kor").transcription_language == "kor"
    assert ChannelsConfig(transcription_language=None).transcription_language is None

    # Invalid values
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="EN")       # uppercase
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="english")   # full word
    with pytest.raises(ValidationError):
        ChannelsConfig(transcription_language="en-US")     # BCP 47 tag


# ---------------------------------------------------------------------------
# _send_with_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_retry_succeeds_first_try():
    """_send_with_retry should succeed on first try and not retry."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            # Succeeds on first try

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")
    await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1


@pytest.mark.asyncio
async def test_send_with_retry_retries_on_failure():
    """_send_with_retry should retry on failure up to max_retries times."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Patch asyncio.sleep to avoid actual delays
    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 3  # 3 total attempts (initial + 2 retries)
    assert mock_sleep.call_count == 2  # 2 sleeps between retries


@pytest.mark.asyncio
async def test_send_with_retry_no_retry_when_max_is_zero():
    """_send_with_retry should not retry when send_max_retries is 0."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=0),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock):
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1  # Called once but no retry (max(0, 1) = 1)


@pytest.mark.asyncio
async def test_send_with_retry_calls_send_delta():
    """_send_with_retry should call send_delta for stream delta events."""
    calls: list[tuple[str, str, str | None, bool, bool]] = []

    class _StreamingChannel(BaseChannel):
        name = "streaming"
        display_name = "Streaming"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass  # Should not be called

        async def send_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
            *,
            stream_id: str | None = None,
            stream_end: bool = False,
            resuming: bool = False,
        ) -> None:
            calls.append((chat_id, delta, stream_id, stream_end, resuming))

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streaming": _StreamingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = outbound_message_for_event(
        channel="streaming",
        chat_id="123",
        event=StreamDeltaEvent(content="test delta", stream_id="s1"),
    )
    await mgr._send_with_retry(mgr.channels["streaming"], msg)
    end = outbound_message_for_event(
        channel="streaming",
        chat_id="123",
        event=StreamEndEvent(content="", stream_id="s1", resuming=True),
    )
    await mgr._send_with_retry(mgr.channels["streaming"], end)

    assert calls == [
        ("123", "test delta", "s1", False, False),
        ("123", "", "s1", True, True),
    ]


@pytest.mark.asyncio
async def test_send_with_retry_skips_send_when_streamed():
    """_send_with_retry should not call send for streamed response events."""
    send_called = False
    send_delta_called = False

    class _StreamedChannel(BaseChannel):
        name = "streamed"
        display_name = "Streamed"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal send_called
            send_called = True

        async def send_delta(
            self,
            chat_id: str,
            delta: str,
            metadata: dict | None = None,
            *,
            stream_id: str | None = None,
            stream_end: bool = False,
            resuming: bool = False,
        ) -> None:
            nonlocal send_delta_called
            send_delta_called = True

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streamed": _StreamedChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = outbound_message_for_event(
        channel="streamed",
        chat_id="123",
        event=StreamedResponseEvent(),
        content="test",
    )
    await mgr._send_with_retry(mgr.channels["streamed"], msg)

    assert send_called is False
    assert send_delta_called is False


def test_outbound_duplicate_suppression_is_scoped_to_origin_message() -> None:
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None
    mgr._origin_reply_fingerprints = {}

    first = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done",
        metadata={"message_id": "msg-1"},
    )
    duplicate = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="  Done  ",
        metadata={"origin_message_id": "msg-1"},
    )
    separate_turn = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done",
        metadata={"message_id": "msg-2"},
    )
    new_origin_content = OutboundMessage(
        channel="feishu",
        chat_id="chat123",
        content="Done with extra details",
        metadata={"origin_message_id": "msg-1"},
    )

    assert mgr._should_suppress_outbound(first) is False
    assert mgr._should_suppress_outbound(duplicate) is True
    assert mgr._should_suppress_outbound(separate_turn) is False
    assert mgr._should_suppress_outbound(new_origin_content) is False


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error():
    """_send_with_retry should re-raise CancelledError for graceful shutdown."""
    class _CancellingChannel(BaseChannel):
        name = "cancelling"
        display_name = "Cancelling"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            raise asyncio.CancelledError("simulated cancellation")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"cancelling": _CancellingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="cancelling", chat_id="123", content="test")

    with pytest.raises(asyncio.CancelledError):
        await mgr._send_with_retry(mgr.channels["cancelling"], msg)


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error_during_sleep():
    """_send_with_retry should re-raise CancelledError during sleep."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Mock sleep to raise CancelledError
    async def cancel_during_sleep(_):
        raise asyncio.CancelledError("cancelled during sleep")

    with patch("nanobot.channels.manager.asyncio.sleep", side_effect=cancel_during_sleep):
        with pytest.raises(asyncio.CancelledError):
            await mgr._send_with_retry(mgr.channels["failing"], msg)

    # Should have attempted once before sleep was cancelled
    assert call_count == 1


# ---------------------------------------------------------------------------
# ChannelManager - lifecycle and getters
# ---------------------------------------------------------------------------

class _ChannelWithAllowFrom(BaseChannel):
    """Channel with configurable allow_from."""
    name = "withallow"
    display_name = "With Allow"

    def __init__(self, config, bus, allow_from):
        super().__init__(config, bus)
        if isinstance(self.config, dict):
            self.config["allow_from"] = allow_from
        else:
            self.config.allow_from = allow_from

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


class _StartableChannel(BaseChannel):
    """Channel that tracks start/stop calls."""
    name = "startable"
    display_name = "Startable"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, msg: OutboundMessage) -> None:
        pass


@pytest.mark.asyncio
async def test_validate_allow_from_allows_empty_list():
    """Empty allow_from is valid now — pairing store handles unapproved senders."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, [])}
    mgr._dispatch_task = None

    # Should not raise — empty list defers to pairing store
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config.allow_from == []


@pytest.mark.asyncio
async def test_validate_allow_from_passes_with_asterisk():
    """_validate_allow_from should not raise when allow_from contains '*'."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, ["*"])}
    mgr._dispatch_task = None

    # Should not raise
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config.allow_from == ["*"]


@pytest.mark.asyncio
async def test_validate_allow_from_allows_empty_dict_allow_from():
    """Empty dict-backed allow_from is valid — pairing store handles approval."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom({"enabled": True}, None, [])}
    mgr._dispatch_task = None

    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert mgr.channels["test"].config["allow_from"] == []


@pytest.mark.asyncio
async def test_validate_allow_from_allows_missing_allow_from():
    """Omitted allowFrom is valid — channel operates in pairing-only mode."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    class _NoAllowFromChannel(BaseChannel):
        name = "noallow"
        display_name = "No Allow"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _NoAllowFromChannel({"enabled": True}, None)}
    mgr._dispatch_task = None

    # Should not raise — pairing-only mode
    mgr._validate_allow_from()
    assert list(mgr.channels) == ["test"]
    assert "allow_from" not in mgr.channels["test"].config


@pytest.mark.asyncio
async def test_get_channel_returns_channel_if_exists():
    """get_channel should return the channel if it exists."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"telegram": _StartableChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    assert mgr.get_channel("telegram") is not None
    assert mgr.get_channel("nonexistent") is None


@pytest.mark.asyncio
async def test_get_status_returns_running_state():
    """get_status should return enabled and running state for each channel."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._dispatch_task = None

    status = mgr.get_status()

    assert status["startable"]["enabled"] is True
    assert status["startable"]["running"] is False  # Not started yet


@pytest.mark.asyncio
async def test_enabled_channels_returns_channel_names():
    """enabled_channels should return list of enabled channel names."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {
        "telegram": _StartableChannel(fake_config, mgr.bus),
        "slack": _StartableChannel(fake_config, mgr.bus),
    }
    mgr._dispatch_task = None

    enabled = mgr.enabled_channels

    assert "telegram" in enabled
    assert "slack" in enabled
    assert len(enabled) == 2


@pytest.mark.asyncio
async def test_stop_all_cancels_dispatcher_and_stops_channels():
    """stop_all should cancel the dispatch task and stop all channels."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._channel_tasks = {}

    # Create a real cancelled task
    async def dummy_task():
        while True:
            await asyncio.sleep(1)

    dispatch_task = asyncio.create_task(dummy_task())
    mgr._dispatch_task = dispatch_task

    await mgr.stop_all()

    # Task should be cancelled
    assert dispatch_task.cancelled()
    # Channel should be stopped
    assert ch.stopped is True


@pytest.mark.asyncio
async def test_start_channel_logs_error_on_failure():
    """_start_channel should log error when channel start fails."""
    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            raise RuntimeError("connection failed")

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None

    ch = _FailingChannel(fake_config, mgr.bus)

    # Should not raise, just log error
    await mgr._start_channel("failing", ch)
    assert mgr.channels == {}
    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_stop_all_handles_channel_exception():
    """stop_all should handle exceptions when stopping channels gracefully."""
    class _StopFailingChannel(BaseChannel):
        name = "stopfailing"
        display_name = "Stop Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            raise RuntimeError("stop failed")

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"stopfailing": _StopFailingChannel(fake_config, mgr.bus)}
    mgr._channel_tasks = {}
    mgr._dispatch_task = None

    # Should not raise even if channel.stop() raises
    await mgr.stop_all()
    assert list(mgr.channels) == ["stopfailing"]
    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_stop_all_handles_channel_stop_cancelled_task():
    """stop_all should treat a channel's already-cancelled internals as stopped."""

    class _StopCancelledChannel(BaseChannel):
        name = "stopcancelled"
        display_name = "Stop Cancelled"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            raise asyncio.CancelledError("server task cancelled")

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    next_channel = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {
        "stopcancelled": _StopCancelledChannel(fake_config, mgr.bus),
        "next": next_channel,
    }
    mgr._channel_tasks = {}
    mgr._dispatch_task = None

    await mgr.stop_all()

    assert next_channel.stopped is True


@pytest.mark.asyncio
async def test_start_all_no_channels_logs_warning():
    """start_all should log warning when no channels are enabled."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}  # No channels
    mgr._dispatch_task = None

    # Should return early without creating dispatch task
    await mgr.start_all()

    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_start_all_creates_dispatch_task():
    """start_all should create the dispatch task when channels exist."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._channel_tasks = {}
    mgr._dispatch_task = None

    # Cancel immediately after start to avoid running forever
    async def cancel_after_start():
        await asyncio.sleep(0.01)
        if mgr._dispatch_task:
            mgr._dispatch_task.cancel()

    cancel_task = asyncio.create_task(cancel_after_start())

    try:
        await mgr.start_all()
    except asyncio.CancelledError:
        pass
    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    # Dispatch task should have been created
    assert mgr._dispatch_task is not None


@pytest.mark.asyncio
async def test_notify_restart_done_waits_until_channel_starts():
    """Restart notice should not be sent before the target channel starts."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    channel = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"feishu": channel}
    mgr._dispatch_task = None
    mgr._send_with_retry = AsyncMock()

    notice = RestartNotice(channel="feishu", chat_id="oc_123", started_at_raw="100.0")
    with patch("nanobot.channels.manager.consume_restart_notice_from_env", return_value=notice):
        task = mgr._notify_restart_done_if_needed()

    await asyncio.sleep(0)
    mgr._send_with_retry.assert_not_awaited()

    channel._running = True
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)

    mgr._send_with_retry.assert_awaited_once()
    sent_channel, sent_msg = mgr._send_with_retry.await_args.args
    assert sent_channel is channel
    assert sent_msg.channel == "feishu"
    assert sent_msg.chat_id == "oc_123"
    assert sent_msg.content.startswith("Restart completed")


@pytest.mark.asyncio
async def test_restart_notice_retries_until_running_channel_accepts_delivery():
    """A running flag must not make an early transport failure final."""

    class _EventuallyDeliverableChannel(_StartableChannel):
        def __init__(self, config, bus):
            super().__init__(config, bus)
            self.attempts = 0
            self.sent: OutboundMessage | None = None

        async def send(self, msg: OutboundMessage) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transport not ready")
            self.sent = msg

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=1),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )
    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    channel = _EventuallyDeliverableChannel(fake_config, mgr.bus)
    channel._running = True
    mgr.channels = {"discord": channel}

    notice = RestartNotice(channel="discord", chat_id="123", started_at_raw="")
    with patch("nanobot.channels.manager._SEND_RETRY_DELAYS", (0,)):
        await mgr._send_restart_notice_when_started(notice, timeout_s=0.1, poll_s=0.01)

    assert channel.attempts == 2
    assert channel.sent is not None
    assert channel.sent.content == "Restart completed."
