from nanobot.channels.telegram import TelegramChannel


def test_telegram_bot_commands_include_provider_and_model() -> None:
    command_names = [command.command for command in TelegramChannel.BOT_COMMANDS]

    assert "provider" in command_names
    assert "model" in command_names
