"""Tests for Telegram channel group policy."""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock

from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig
from nanobot.bus.queue import MessageBus


def _make_config(
    group_policy: str = "disabled",
    group_allow_from: list[str] | None = None,
    allow_from: list[str] | None = None,
) -> TelegramConfig:
    """Create a test TelegramConfig."""
    return TelegramConfig(
        enabled=True,
        token="test_token",
        allow_from=allow_from or [],
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
    )


def _make_channel(config: TelegramConfig) -> TelegramChannel:
    """Create a TelegramChannel with mocked bus."""
    bus = Mock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    channel = TelegramChannel(config, bus)

    # Mock the app and bot for mention checking
    channel._app = Mock()
    channel._app.bot = Mock()
    channel._app.bot.username = "testbot"

    return channel


class TestGroupPolicyDisabled:
    """Test group_policy='disabled' mode."""

    def test_blocks_all_group_messages(self):
        config = _make_config(group_policy="disabled")
        channel = _make_channel(config)

        assert not channel._is_allowed_group("-1001234567890", "hello")
        assert not channel._is_allowed_group("-1001234567890", "@testbot hello")


class TestGroupPolicyOpen:
    """Test group_policy='open' mode."""

    def test_allows_all_group_messages(self):
        config = _make_config(group_policy="open")
        channel = _make_channel(config)

        assert channel._is_allowed_group("-1001234567890", "hello")
        assert channel._is_allowed_group("-1009999999999", "world")


class TestGroupPolicyMention:
    """Test group_policy='mention' mode."""

    def test_requires_bot_mention(self):
        config = _make_config(group_policy="mention")
        channel = _make_channel(config)

        # Without mention
        assert not channel._is_allowed_group("-1001234567890", "hello")
        assert not channel._is_allowed_group("-1001234567890", "hello @otherbot")

        # With mention
        assert channel._is_allowed_group("-1001234567890", "@testbot hello")
        assert channel._is_allowed_group("-1001234567890", "hello @testbot")
        assert channel._is_allowed_group("-1001234567890", "@testbot")


class TestGroupPolicyAllowlist:
    """Test group_policy='allowlist' mode."""

    def test_allows_only_listed_groups(self):
        config = _make_config(
            group_policy="allowlist",
            group_allow_from=["-1001234567890", "-1009999999999"]
        )
        channel = _make_channel(config)

        # Allowed groups
        assert channel._is_allowed_group("-1001234567890", "hello")
        assert channel._is_allowed_group("-1009999999999", "world")

        # Not allowed
        assert not channel._is_allowed_group("-1008888888888", "hello")


class TestGroupAllowFromFilter:
    """Test that group_allow_from acts as additional filter for all policies."""

    def test_open_policy_with_allowlist_filter(self):
        """Even with 'open' policy, group_allow_from restricts groups."""
        config = _make_config(
            group_policy="open",
            group_allow_from=["-1001234567890"]
        )
        channel = _make_channel(config)

        # Only allowed in specified group
        assert channel._is_allowed_group("-1001234567890", "hello")
        assert not channel._is_allowed_group("-1009999999999", "hello")

    def test_mention_policy_with_allowlist_filter(self):
        """Mention policy + group_allow_from = mention required AND group must be in list."""
        config = _make_config(
            group_policy="mention",
            group_allow_from=["-1001234567890"]
        )
        channel = _make_channel(config)

        # Allowed group + mention
        assert channel._is_allowed_group("-1001234567890", "@testbot hello")

        # Allowed group but no mention
        assert not channel._is_allowed_group("-1001234567890", "hello")

        # Mention but not in allowed groups
        assert not channel._is_allowed_group("-1009999999999", "@testbot hello")

    def test_empty_allowlist_means_all_groups(self):
        """Empty group_allow_from should not filter any groups."""
        config = _make_config(
            group_policy="open",
            group_allow_from=[]
        )
        channel = _make_channel(config)

        # Should allow any group when allowlist is empty
        assert channel._is_allowed_group("-1001234567890", "hello")
        assert channel._is_allowed_group("-1009999999999", "hello")


class TestSenderIdMethod:
    """Test _sender_id static method."""

    def test_sender_id_with_username(self):
        user = Mock()
        user.id = 123456789
        user.username = "alice"

        result = TelegramChannel._sender_id(user)
        assert result == "123456789|alice"

    def test_sender_id_without_username(self):
        user = Mock()
        user.id = 123456789
        user.username = None

        result = TelegramChannel._sender_id(user)
        assert result == "123456789"
