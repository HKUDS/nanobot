from types import SimpleNamespace

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _StubChannel(BaseChannel):
    def __init__(self, config, bus, **kwargs):
        super().__init__(config, bus)
        self.kwargs = kwargs

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, message) -> None:
        return None


def test_builtin_channel_registry_registers_current_channels_and_extra_kwargs() -> None:
    from nanobot.channels.builtins import BUILTIN_CHANNEL_REGISTRY

    config = Config()
    config.providers.groq.api_key = "groq-test-key"

    specs = BUILTIN_CHANNEL_REGISTRY.all()

    assert [spec.name for spec in specs] == [
        "telegram",
        "whatsapp",
        "discord",
        "feishu",
        "mochat",
        "dingtalk",
        "email",
        "slack",
        "qq",
        "matrix",
    ]
    assert BUILTIN_CHANNEL_REGISTRY.get("telegram").extra_kwargs_factory(config) == {
        "groq_api_key": "groq-test-key"
    }
    assert BUILTIN_CHANNEL_REGISTRY.get("feishu").extra_kwargs_factory(config) == {
        "groq_api_key": "groq-test-key"
    }
    assert BUILTIN_CHANNEL_REGISTRY.get("discord").extra_kwargs_factory(config) == {}


def test_builtin_channel_factory_builds_enabled_channels(monkeypatch) -> None:
    from nanobot.channels.factory import BuiltinChannelFactory

    created = []

    class TelegramChannel(_StubChannel):
        def __init__(self, config, bus, **kwargs):
            super().__init__(config, bus, **kwargs)
            created.append(("telegram", config, bus, kwargs))

    class DiscordChannel(_StubChannel):
        def __init__(self, config, bus, **kwargs):
            super().__init__(config, bus, **kwargs)
            created.append(("discord", config, bus, kwargs))

    modules = {
        "nanobot.channels.telegram": SimpleNamespace(TelegramChannel=TelegramChannel),
        "nanobot.channels.discord": SimpleNamespace(DiscordChannel=DiscordChannel),
    }

    monkeypatch.setattr(
        "nanobot.channels.factory.importlib.import_module",
        lambda module_path: modules[module_path],
    )

    config = Config()
    config.providers.groq.api_key = "groq-test-key"
    config.channels.telegram.enabled = True
    config.channels.discord.enabled = True
    bus = MessageBus()

    channels = BuiltinChannelFactory().build_enabled_channels(config, bus)

    assert list(channels) == ["telegram", "discord"]
    assert created == [
        (
            "telegram",
            config.channels.telegram,
            bus,
            {"groq_api_key": "groq-test-key"},
        ),
        ("discord", config.channels.discord, bus, {}),
    ]


def test_builtin_channel_factory_skips_channel_when_class_is_missing(monkeypatch) -> None:
    from nanobot.channels.factory import BuiltinChannelFactory
    from nanobot.channels.registry import ChannelRegistry, ChannelSpec

    warnings = []
    registry = ChannelRegistry()
    registry.register(
        ChannelSpec(
            name="telegram",
            module_path="nanobot.channels.telegram",
            class_name="MissingTelegramChannel",
            display_name="Telegram",
        )
    )

    monkeypatch.setattr(
        "nanobot.channels.factory.importlib.import_module",
        lambda _module_path: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "nanobot.channels.factory.logger.warning",
        lambda message, display_name, error: warnings.append((message, display_name, str(error))),
    )

    config = Config()
    config.channels.telegram.enabled = True

    channels = BuiltinChannelFactory(registry).build_enabled_channels(config, MessageBus())

    assert channels == {}
    assert warnings == [
        (
            "{} channel not available: {}",
            "Telegram",
            "'types.SimpleNamespace' object has no attribute 'MissingTelegramChannel'",
        )
    ]


def test_channel_manager_builds_channels_through_factory(monkeypatch) -> None:
    calls = []
    bus = MessageBus()
    config = Config()

    class FakeFactory:
        def build_enabled_channels(self, runtime_config, runtime_bus):
            calls.append((runtime_config, runtime_bus))
            return {
                "telegram": _StubChannel(
                    SimpleNamespace(allow_from=["*"]),
                    runtime_bus,
                )
            }

    monkeypatch.setattr("nanobot.channels.manager.BuiltinChannelFactory", FakeFactory)

    manager = ChannelManager(config, bus)

    assert calls == [(config, bus)]
    assert list(manager.channels) == ["telegram"]
