from nanobot.channels.policy import should_deliver_message
from nanobot.config.schema import ChannelsConfig


def test_should_deliver_message_allows_non_progress_messages() -> None:
    config = ChannelsConfig(send_progress=False, send_tool_hints=False)

    assert should_deliver_message(config, {}) is True


def test_should_deliver_message_blocks_progress_when_disabled() -> None:
    config = ChannelsConfig(send_progress=False)

    assert should_deliver_message(config, {"_progress": True}) is False


def test_should_deliver_message_blocks_tool_hints_when_disabled() -> None:
    config = ChannelsConfig(send_tool_hints=False)

    assert (
        should_deliver_message(
            config,
            {"_progress": True, "_tool_hint": True},
        )
        is False
    )


def test_should_deliver_message_allows_tool_hints_independently_of_progress() -> None:
    config = ChannelsConfig(send_progress=False, send_tool_hints=True)

    assert (
        should_deliver_message(
            config,
            {"_progress": True, "_tool_hint": True},
        )
        is True
    )


def test_should_deliver_message_allows_messages_without_channels_config() -> None:
    assert should_deliver_message(None, {"_progress": True, "_tool_hint": True}) is True
