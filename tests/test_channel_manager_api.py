from nanobot.bus.queue import MessageBus
from nanobot.channels.api import APIChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


def test_channel_manager_initializes_api_channel() -> None:
    config = Config()
    config.channels.api.enabled = True
    config.channels.api.allow_from = ["*"]
    config.channels.api.path = "/chat"
    config.gateway.host = "127.0.0.1"
    config.gateway.port = 18888

    manager = ChannelManager(config, MessageBus())

    channel = manager.get_channel("api")
    assert isinstance(channel, APIChannel)
    assert channel.host == "127.0.0.1"
    assert channel.port == 18888
