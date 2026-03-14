from dataclasses import is_dataclass
from typing import get_type_hints

import pytest

from nanobot.channels import ChannelRegistry, ChannelSpec
from nanobot.config.schema import Config


def test_channel_spec_and_registry_preserve_registration_order() -> None:
    telegram = ChannelSpec(
        name="telegram",
        module_path="nanobot.channels.telegram",
        class_name="TelegramChannel",
    )
    discord = ChannelSpec(
        name="discord",
        module_path="nanobot.channels.discord",
        class_name="DiscordChannel",
        display_name="Discord",
    )
    registry = ChannelRegistry()

    registry.register(telegram)
    registry.register(discord)

    assert is_dataclass(telegram) is True
    assert telegram.module_path == "nanobot.channels.telegram"
    assert telegram.class_name == "TelegramChannel"
    assert telegram.display_name == ""
    assert telegram.extra_kwargs_factory(object()) == {}
    assert discord.display_name == "Discord"
    assert registry.get("telegram") is telegram
    assert registry.get("discord") is discord
    assert registry.all() == (telegram, discord)


def test_channel_spec_supports_extra_kwargs_factory() -> None:
    config = Config()
    config.channels.telegram.enabled = True
    config.channels.telegram.proxy = "socks5://127.0.0.1:1080"
    config.agents.defaults.workspace = "~/runtime-workspace"

    spec = ChannelSpec(
        name="telegram",
        module_path="nanobot.channels.telegram",
        class_name="TelegramChannel",
        extra_kwargs_factory=lambda runtime_config: {
            "proxy": runtime_config.channels.telegram.proxy,
            "workspace": runtime_config.agents.defaults.workspace,
        },
    )

    assert spec.extra_kwargs_factory(config) == {
        "proxy": "socks5://127.0.0.1:1080",
        "workspace": "~/runtime-workspace",
    }


def test_channel_spec_extra_kwargs_factory_is_typed_for_root_config() -> None:
    extra_kwargs_factory_type = get_type_hints(ChannelSpec)["extra_kwargs_factory"]

    assert "Config" in str(extra_kwargs_factory_type)


@pytest.mark.parametrize(
    ("field_name", "name", "module_path", "class_name"),
    [
        (
            "name",
            "",
            "nanobot.channels.telegram",
            "TelegramChannel",
        ),
        (
            "module_path",
            "telegram",
            "",
            "TelegramChannel",
        ),
        (
            "class_name",
            "telegram",
            "nanobot.channels.telegram",
            "",
        ),
    ],
)
def test_channel_spec_rejects_blank_required_fields(
    field_name: str,
    name: str,
    module_path: str,
    class_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        ChannelSpec(name=name, module_path=module_path, class_name=class_name)


def test_channel_registry_rejects_duplicate_names() -> None:
    registry = ChannelRegistry()
    registry.register(
        ChannelSpec(
            name="telegram",
            module_path="nanobot.channels.telegram",
            class_name="TelegramChannel",
        )
    )

    with pytest.raises(ValueError, match="telegram"):
        registry.register(
            ChannelSpec(
                name="telegram",
                module_path="nanobot.channels.alt_telegram",
                class_name="AlternateTelegramChannel",
            )
        )


def test_channel_registry_returns_none_for_unknown_name() -> None:
    registry = ChannelRegistry()

    assert registry.get("missing") is None
