from nanobot.channels.telegram import TelegramChannel


def test_telegram_bot_commands_include_model() -> None:
    command_names = [command.command for command in TelegramChannel.BOT_COMMANDS]

    assert "model" in command_names
