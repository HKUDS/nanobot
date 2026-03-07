"""Tests for Telegram group sender identification."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.telegram import TelegramChannel


class FakeUser:
    """Minimal Telegram user stub."""

    def __init__(self, user_id: int, first_name: str = "", username: str = ""):
        self.id = user_id
        self.first_name = first_name
        self.username = username


# --- _format_group_content ---


def test_group_message_prefixed_with_first_name() -> None:
    user = FakeUser(123, first_name="Andrise")
    result = TelegramChannel._format_group_content("Bom dia", user, is_group=True)
    assert result == "[Andrise]: Bom dia"


def test_private_message_unchanged() -> None:
    user = FakeUser(123, first_name="Andrise")
    result = TelegramChannel._format_group_content("Bom dia", user, is_group=False)
    assert result == "Bom dia"


def test_fallback_to_username_when_no_first_name() -> None:
    user = FakeUser(123, username="tiktoby")
    result = TelegramChannel._format_group_content("Hello", user, is_group=True)
    assert result == "[tiktoby]: Hello"


def test_fallback_to_user_id_when_no_name() -> None:
    user = FakeUser(8501561624)
    result = TelegramChannel._format_group_content("Hello", user, is_group=True)
    assert result == "[8501561624]: Hello"


def test_group_media_content_prefixed() -> None:
    user = FakeUser(123, first_name="Toby")
    content = "Check this\n[image: /home/ubuntu/.nanobot/media/photo.jpg]"
    result = TelegramChannel._format_group_content(content, user, is_group=True)
    assert result == f"[Toby]: {content}"


def test_group_empty_message_prefixed() -> None:
    user = FakeUser(123, first_name="Andrei")
    result = TelegramChannel._format_group_content("[empty message]", user, is_group=True)
    assert result == "[Andrei]: [empty message]"


def test_first_name_takes_priority_over_username() -> None:
    user = FakeUser(123, first_name="Saimon", username="tiktoby")
    result = TelegramChannel._format_group_content("Hi", user, is_group=True)
    assert result == "[Saimon]: Hi"
