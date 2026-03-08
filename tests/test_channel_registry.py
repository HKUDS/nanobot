from dataclasses import is_dataclass

import pytest

from nanobot.channels import ChannelRegistry, ChannelSpec


def test_channel_spec_and_registry_preserve_registration_order() -> None:
    telegram = ChannelSpec(name="telegram", module="nanobot.channels.telegram")
    discord = ChannelSpec(name="discord", module="nanobot.channels.discord")
    registry = ChannelRegistry()

    registry.register(telegram)
    registry.register(discord)

    assert is_dataclass(telegram) is True
    assert registry.get("telegram") is telegram
    assert registry.get("discord") is discord
    assert registry.all() == (telegram, discord)


def test_channel_registry_rejects_duplicate_names() -> None:
    registry = ChannelRegistry()
    registry.register(ChannelSpec(name="telegram", module="nanobot.channels.telegram"))

    with pytest.raises(ValueError, match="telegram"):
        registry.register(ChannelSpec(name="telegram", module="nanobot.channels.alt_telegram"))
