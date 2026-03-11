"""Test channels status command."""
from unittest.mock import patch

from nanobot.cli.commands import channels_status


def test_channels_status_includes_matrix():
    """Test that channels status command includes Matrix channel."""
    with patch("nanobot.config.loader.load_config") as mock_load_config, \
         patch("nanobot.cli.commands.console") as mock_console:

        # Mock config with default values
        from nanobot.config.schema import Config
        mock_config = Config()
        mock_load_config.return_value = mock_config

        # Call the command
        channels_status()

        # Verify console.print was called
        assert mock_console.print.called

        # Get the table that was printed
        table = mock_console.print.call_args[0][0]

        # Convert table to string to check content
        from io import StringIO
        from rich.console import Console

        string_io = StringIO()
        temp_console = Console(file=string_io, force_terminal=True)
        temp_console.print(table)
        output = string_io.getvalue()

        # Verify Matrix is in the output
        assert "Matrix" in output, "Matrix should be included in channels status output"

        # Verify all expected channels are present
        expected_channels = [
            "WhatsApp", "Discord", "Matrix", "Feishu", "Mochat",
            "Telegram", "Slack", "DingTalk", "QQ", "Email"
        ]
        for channel in expected_channels:
            assert channel in output, f"{channel} should be in channels status output"
