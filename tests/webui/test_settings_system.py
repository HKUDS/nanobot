from __future__ import annotations

import pytest

from nanobot.channels.contracts import channel_default_config, channel_instance_specs
from nanobot.channels.manager import ChannelManager
from nanobot.channels.registry import load_channel_plugin
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_system import (
    coerce_channel_value,
    save_channel_config_values,
    system_settings_payload,
    update_agent_system_settings,
)


def test_system_domain_owns_runtime_dto_and_agent_updates(tmp_path) -> None:
    config = Config()

    changed, restart_required = update_agent_system_settings(
        config,
        {
            "timezone": ["Asia/Shanghai"],
            "tool_hint_max_length": ["120"],
        },
    )
    payload = system_settings_payload(
        config,
        config_path=tmp_path / "config.json",
        version="0.3.0",
    )

    assert changed is True
    assert restart_required is True
    assert config.agents.defaults.timezone == "Asia/Shanghai"
    assert config.agents.defaults.timezone_mode == "manual"
    assert config.agents.defaults.tool_hint_max_length == 120
    assert payload["runtime"]["config_path"] == str(tmp_path / "config.json")
    assert payload["version"] == {"current": "0.3.0"}
    assert payload["docs"]["version"] == "0.3.0"
    assert set(payload) == {"runtime", "runtime_config", "usage", "advanced", "version", "docs"}


def test_system_domain_validates_channel_field_values() -> None:
    assert coerce_channel_value("allow_from", "alice, bob", "list") == [
        "alice",
        "bob",
    ]
    assert coerce_channel_value("enabled", "yes", "bool") is True
    assert coerce_channel_value("port", "8765", "int") == 8765
    assert coerce_channel_value("delay", "0.6", "float") == 0.6
    assert coerce_channel_value("overrides", '{"123": "open"}', "json") == {
        "123": "open"
    }
    assert coerce_channel_value("token", None, "secret") == ""


def test_channel_secret_is_cleared_only_by_explicit_null() -> None:
    config = Config.model_validate({
        "channels": {"matrix": {"password": "saved-password"}},
    })

    saved = save_channel_config_values(
        config,
        "matrix",
        {"channels.matrix.password": None},
        load_channel_plugin=load_channel_plugin,
    )

    assert saved == ["channels.matrix.password"]
    assert config.channels.matrix["password"] == ""


@pytest.mark.parametrize("existing_key", ["showCompactionNotices", "show_compaction_notices"])
def test_compaction_notice_webui_contract_and_config_round_trip(existing_key, tmp_path):
    name = "qq"
    plugin = load_channel_plugin(name)
    spec = plugin.setup
    field = next(item for item in spec.to_public_dict(name)["fields"]
                 if item["field"] == "showCompactionNotices")
    assert field["kind"] == "bool"
    assert field["inheritable"] is True
    assert "default_value" not in field
    assert channel_default_config(plugin).get("showCompactionNotices") is None
    config = Config.model_validate({
        "channels": {"showCompactionNotices": True, name: {existing_key: False}},
    })
    key = f"channels.{name}.showCompactionNotices"
    manager = ChannelManager.__new__(ChannelManager)
    # The generic settings route must preserve false, true and a return to inheritance.
    for submitted, expected in [("false", False), ("true", True), ("", None), (None, None)]:
        save_channel_config_values(
            config, name, {key: submitted}, load_channel_plugin=load_channel_plugin,
        )
        config_path = tmp_path / "config.json"
        save_config(config, config_path)
        config = load_config(config_path)
        assert config.channels.show_compaction_notices is True
        section = getattr(config.channels, name)
        [instance] = channel_instance_specs(plugin, section, enabled_only=False)
        assert instance.config.get("showCompactionNotices") is expected
        assert "show_compaction_notices" not in instance.config
        if expected is None:
            # Inheritance is persisted as absence, also readable by older QQ versions.
            assert "showCompactionNotices" not in instance.config
        assert manager._resolve_bool_override(
            instance.config, "show_compaction_notices", True,
        ) is (True if expected is None else expected)


def test_saving_other_qq_settings_does_not_pin_the_global_notice_policy():
    config = Config.model_validate({"channels": {"showCompactionNotices": True}})
    save_channel_config_values(
        config, "qq", {"appId": "a", "secret": "s"}, load_channel_plugin=load_channel_plugin,
    )
    assert config.channels.qq.get("showCompactionNotices") is None
