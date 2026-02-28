"""Unit tests for Telegram keyboard functionality."""

import pytest
from unittest.mock import MagicMock, patch

from nanobot.config.schema import TelegramConfig
from nanobot.channels.telegram import TelegramChannel


class TestBuildKeyboard:
    """Tests for _build_keyboard method."""
    
    def test_no_buttons_returns_none(self):
        """Empty buttons should return None."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=False)
        channel = TelegramChannel(config, MagicMock())
        
        result = channel._build_keyboard([])
        
        assert result is None
    
    def test_no_buttons_none_input(self):
        """None input should return None."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=False)
        channel = TelegramChannel(config, MagicMock())
        
        result = channel._build_keyboard(None)
        
        assert result is None
    
    def test_disabled_returns_none(self):
        """Should return None when keyboard_buttons_enabled=False."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=False)
        channel = TelegramChannel(config, MagicMock())
        
        # buttons format: [[(label, callback_data), ...], ...]
        buttons = [
            [("Yes", "yes"), ("No", "no")],
            [("Maybe", "maybe")],
        ]
        
        result = channel._build_keyboard(buttons)
        
        # Should be None when disabled
        assert result is None
    
    def test_inline_keyboard_when_enabled(self):
        """Should build InlineKeyboardMarkup when keyboard_buttons_enabled=True."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        channel = TelegramChannel(config, MagicMock())
        
        buttons = [
            [("Yes", "yes"), ("No", "no")],
            [("Maybe", "maybe")],
        ]
        
        result = channel._build_keyboard(buttons)
        
        # Should be InlineKeyboardMarkup
        assert result is not None
        assert hasattr(result, 'inline_keyboard')
    
    def test_inline_keyboard_button_uses_callback_data(self):
        """Inline keyboard buttons should use second tuple element as callback_data."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        channel = TelegramChannel(config, MagicMock())

        buttons = [[("My Button", "custom_callback")]]

        result = channel._build_keyboard(buttons)

        # Check that callback_data uses the second tuple element
        button = result.inline_keyboard[0][0]
        assert button.text == "My Button"
        assert button.callback_data == "custom_callback"

    def test_inline_keyboard_button_defaults_to_label(self):
        """Inline keyboard buttons without tuple should use label as callback_data."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        channel = TelegramChannel(config, MagicMock())

        buttons = [["Simple Button"]]

        result = channel._build_keyboard(buttons)

        button = result.inline_keyboard[0][0]
        assert button.text == "Simple Button"
        assert button.callback_data == "Simple Button"
    
    def test_single_row_buttons(self):
        """Should handle single row of buttons."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        channel = TelegramChannel(config, MagicMock())
        
        buttons = [[("A", "a"), ("B", "b"), ("C", "c")]]
        
        result = channel._build_keyboard(buttons)
        
        assert len(result.inline_keyboard) == 1
        assert len(result.inline_keyboard[0]) == 3
    
    def test_multiple_rows_buttons(self):
        """Should handle multiple rows of buttons."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        channel = TelegramChannel(config, MagicMock())
        
        buttons = [
            [("Row1_A", "r1a"), ("Row1_B", "r1b")],
            [("Row2_A", "r2a")],
            [("Row3_A", "r3a"), ("Row3_B", "r3b"), ("Row3_C", "r3c")],
        ]
        
        result = channel._build_keyboard(buttons)
        
        assert len(result.inline_keyboard) == 3
        assert len(result.inline_keyboard[0]) == 2
        assert len(result.inline_keyboard[1]) == 1
        assert len(result.inline_keyboard[2]) == 3


class TestConfigKey:
    """Tests for config key naming."""
    
    def test_config_default_false(self):
        """Default should be False (disabled)."""
        config = TelegramConfig(token="test")
        
        assert config.keyboard_buttons_enabled is False
    
    def test_config_can_enable(self):
        """Should be able to enable via config."""
        config = TelegramConfig(token="test", keyboard_buttons_enabled=True)
        
        assert config.keyboard_buttons_enabled is True
