"""Tests for Feishu _is_bot_mentioned logic."""

from types import SimpleNamespace

import pytest

from nanobot.channels.feishu import FeishuChannel


def _make_channel(bot_open_id: str | None = None) -> FeishuChannel:
    config = SimpleNamespace(
        app_id="test_id",
        app_secret="test_secret",
        verification_token="",
        event_encrypt_key="",
        group_policy="mention",
    )
    ch = FeishuChannel.__new__(FeishuChannel)
    ch.config = config
    ch._bot_open_id = bot_open_id
    return ch


def _make_message(mentions=None, content="hello"):
    return SimpleNamespace(content=content, mentions=mentions)


def _make_mention(open_id: str, user_id: str | None = None):
    mid = SimpleNamespace(open_id=open_id, user_id=user_id)
    return SimpleNamespace(id=mid)


class TestIsBotMentioned:
    def test_exact_match_with_bot_open_id(self):
        ch = _make_channel(bot_open_id="ou_bot123")
        msg = _make_message(mentions=[_make_mention("ou_bot123")])
        assert ch._is_bot_mentioned(msg) is True

    def test_no_match_different_bot(self):
        ch = _make_channel(bot_open_id="ou_bot123")
        msg = _make_message(mentions=[_make_mention("ou_other_bot")])
        assert ch._is_bot_mentioned(msg) is False

    def test_at_all_always_matches(self):
        ch = _make_channel(bot_open_id="ou_bot123")
        msg = _make_message(content="@_all hello")
        assert ch._is_bot_mentioned(msg) is True

    def test_fallback_heuristic_when_no_bot_open_id(self):
        ch = _make_channel(bot_open_id=None)
        msg = _make_message(mentions=[_make_mention("ou_some_bot", user_id=None)])
        assert ch._is_bot_mentioned(msg) is True

    def test_fallback_ignores_user_mentions(self):
        ch = _make_channel(bot_open_id=None)
        msg = _make_message(mentions=[_make_mention("ou_user", user_id="u_12345")])
        assert ch._is_bot_mentioned(msg) is False

    def test_no_mentions_returns_false(self):
        ch = _make_channel(bot_open_id="ou_bot123")
        msg = _make_message(mentions=None)
        assert ch._is_bot_mentioned(msg) is False
