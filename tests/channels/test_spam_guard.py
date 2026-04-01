"""Tests for ChannelManager spam guard (dedup of repeated messages)."""
import time
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import SpamGuardConfig


def _make_manager(enabled=True, window_s=300, max_repeats=2):
    """Create a ChannelManager with spam guard config (no actual channels)."""
    mgr = object.__new__(ChannelManager)
    mgr._dedup_log = {}
    mgr._dedup_last_cleanup = 0.0
    mgr.config = MagicMock()
    mgr.config.channels.spam_guard = SpamGuardConfig(
        enabled=enabled, window_s=window_s, max_repeats=max_repeats,
    )
    return mgr


def _msg(content="hello", channel="whatsapp", chat_id="user1", metadata=None):
    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content=content,
        metadata=metadata or {},
    )


class TestSpamGuard:
    def test_first_message_not_spam(self):
        mgr = _make_manager()
        assert mgr._is_spam(_msg()) is False

    def test_second_identical_message_not_spam(self):
        mgr = _make_manager()
        mgr._is_spam(_msg())
        assert mgr._is_spam(_msg()) is False

    def test_third_identical_message_is_spam(self):
        mgr = _make_manager()
        mgr._is_spam(_msg())
        mgr._is_spam(_msg())
        assert mgr._is_spam(_msg()) is True

    def test_different_content_not_spam(self):
        mgr = _make_manager()
        mgr._is_spam(_msg("hello"))
        mgr._is_spam(_msg("hello"))
        assert mgr._is_spam(_msg("world")) is False

    def test_different_recipient_not_spam(self):
        mgr = _make_manager()
        mgr._is_spam(_msg(chat_id="user1"))
        mgr._is_spam(_msg(chat_id="user1"))
        assert mgr._is_spam(_msg(chat_id="user2")) is False

    def test_different_channel_not_spam(self):
        mgr = _make_manager()
        mgr._is_spam(_msg(channel="whatsapp"))
        mgr._is_spam(_msg(channel="whatsapp"))
        assert mgr._is_spam(_msg(channel="telegram")) is False

    def test_stream_delta_exempt(self):
        mgr = _make_manager()
        delta = _msg(metadata={"_stream_delta": True})
        for _ in range(5):
            assert mgr._is_spam(delta) is False

    def test_stream_end_exempt(self):
        mgr = _make_manager()
        end = _msg(metadata={"_stream_end": True})
        for _ in range(5):
            assert mgr._is_spam(end) is False

    def test_progress_exempt(self):
        mgr = _make_manager()
        progress = _msg(metadata={"_progress": True})
        for _ in range(5):
            assert mgr._is_spam(progress) is False

    def test_empty_content_exempt(self):
        mgr = _make_manager()
        empty = _msg(content="")
        for _ in range(5):
            assert mgr._is_spam(empty) is False

    def test_whitespace_only_exempt(self):
        mgr = _make_manager()
        ws = _msg(content="   \n  ")
        for _ in range(5):
            assert mgr._is_spam(ws) is False

    def test_expires_after_window(self):
        mgr = _make_manager(window_s=300)
        mgr._is_spam(_msg())
        mgr._is_spam(_msg())
        assert mgr._is_spam(_msg()) is True

        with patch("time.monotonic", return_value=time.monotonic() + 301):
            assert mgr._is_spam(_msg()) is False

    def test_custom_max_repeats(self):
        mgr = _make_manager(max_repeats=5)
        for _ in range(5):
            assert mgr._is_spam(_msg()) is False
        assert mgr._is_spam(_msg()) is True

    def test_custom_window(self):
        mgr = _make_manager(window_s=10)
        mgr._is_spam(_msg())
        mgr._is_spam(_msg())
        assert mgr._is_spam(_msg()) is True

        with patch("time.monotonic", return_value=time.monotonic() + 11):
            assert mgr._is_spam(_msg()) is False

    def test_content_whitespace_normalized(self):
        mgr = _make_manager()
        mgr._is_spam(_msg(content="  hello world  "))
        mgr._is_spam(_msg(content="hello world"))
        assert mgr._is_spam(_msg(content="  hello world\n")) is True

    def test_disabled_by_default(self):
        """When disabled, _is_spam should still work but dispatch won't call it."""
        mgr = _make_manager(enabled=False)
        # _is_spam itself still functions — it's the dispatch that checks enabled
        assert mgr._is_spam(_msg()) is False
