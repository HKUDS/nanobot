from dataclasses import is_dataclass

import pytest

from nanobot.channels import ChannelRegistry, ChannelSpec


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
    config = {
        "telegram": {"api_base": "https://example.invalid"},
        "shared": {"proxy": "socks5://127.0.0.1:1080"},
    }
    spec = ChannelSpec(
        name="telegram",
        module_path="nanobot.channels.telegram",
        class_name="TelegramChannel",
        extra_kwargs_factory=lambda runtime_config: {
            "api_base": runtime_config["telegram"]["api_base"],
            "proxy": runtime_config["shared"]["proxy"],
        },
    )

    assert spec.extra_kwargs_factory(config) == {
        "api_base": "https://example.invalid",
        "proxy": "socks5://127.0.0.1:1080",
    }


@pytest.mark.parametrize(
    ("field_name", "kwargs"),
    [
        (
            "name",
            {
                "name": "",
                "module_path": "nanobot.channels.telegram",
                "class_name": "TelegramChannel",
            },
        ),
        (
            "module_path",
            {
                "name": "telegram",
                "module_path": "",
                "class_name": "TelegramChannel",
            },
        ),
        (
            "class_name",
            {
                "name": "telegram",
                "module_path": "nanobot.channels.telegram",
                "class_name": "",
            },
        ),
    ],
)
def test_channel_spec_rejects_blank_required_fields(
    field_name: str,
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match=field_name):
        ChannelSpec(**kwargs)


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
