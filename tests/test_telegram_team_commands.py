from nanobot.channels.telegram import TelegramChannel
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import TelegramConfig


def test_telegram_bot_commands_include_team_and_btw():
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    names = {c.command for c in channel.BOT_COMMANDS}
    assert "team" in names
    assert "btw" in names
