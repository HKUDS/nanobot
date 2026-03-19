"""Tests for Feishu group mention detection fix."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig


def _make_channel(bot_open_id: str | None = "ou_bot123") -> FeishuChannel:
    config = FeishuConfig(enabled=True, app_id="cli_test", app_secret="secret", allow_from=["*"])
    channel = FeishuChannel(config, MessageBus())
    channel._client = MagicMock()
    channel._bot_open_id = bot_open_id
    return channel


def _make_mention(open_id: str | None = None, user_id: str | None = None):
    mid = SimpleNamespace(open_id=open_id, user_id=user_id)
    return SimpleNamespace(id=mid)


def _make_message(mentions: list, content: str = '{"text": "hello"}'):
    return SimpleNamespace(mentions=mentions, content=content)


# ── Default value ────────────────────────────────────────────────────────────

def test_bot_open_id_is_none_by_default() -> None:
    config = FeishuConfig(enabled=True, app_id="x", app_secret="x", allow_from=["*"])
    channel = FeishuChannel(config, MessageBus())
    assert channel._bot_open_id is None


# ── Exact match mode (bot_open_id known) ─────────────────────────────────────

def test_is_bot_mentioned_exact_match_returns_true() -> None:
    channel = _make_channel(bot_open_id="ou_bot123")
    msg = _make_message(mentions=[_make_mention(open_id="ou_bot123", user_id=None)])
    assert channel._is_bot_mentioned(msg) is True


def test_is_bot_mentioned_exact_mismatch_returns_false() -> None:
    """Other user mentioned, not the bot."""
    channel = _make_channel(bot_open_id="ou_bot123")
    msg = _make_message(mentions=[_make_mention(open_id="ou_user456", user_id="u456")])
    assert channel._is_bot_mentioned(msg) is False


def test_is_bot_mentioned_external_user_no_user_id_returns_false() -> None:
    """External/guest user with no user_id but valid open_id — must NOT trigger."""
    channel = _make_channel(bot_open_id="ou_bot123")
    msg = _make_message(mentions=[_make_mention(open_id="ou_external999", user_id=None)])
    assert channel._is_bot_mentioned(msg) is False


def test_is_bot_mentioned_no_mentions_returns_false() -> None:
    channel = _make_channel(bot_open_id="ou_bot123")
    msg = _make_message(mentions=[])
    assert channel._is_bot_mentioned(msg) is False


# ── Fallback heuristic mode (bot_open_id unknown) ────────────────────────────

def test_is_bot_mentioned_fallback_no_user_id_with_ou_prefix_returns_true() -> None:
    channel = _make_channel(bot_open_id=None)
    msg = _make_message(mentions=[_make_mention(open_id="ou_bot123", user_id=None)])
    assert channel._is_bot_mentioned(msg) is True


def test_is_bot_mentioned_fallback_with_user_id_returns_false() -> None:
    channel = _make_channel(bot_open_id=None)
    msg = _make_message(mentions=[_make_mention(open_id="ou_user456", user_id="u456")])
    assert channel._is_bot_mentioned(msg) is False


# ── @_all shortcut ───────────────────────────────────────────────────────────

def test_is_bot_mentioned_at_all_returns_true() -> None:
    channel = _make_channel(bot_open_id="ou_bot123")
    msg = _make_message(mentions=[], content='{"text": "@_all hello"}')
    assert channel._is_bot_mentioned(msg) is True


# ── _fetch_bot_open_id_sync — API failure fallback (spec case 5) ─────────────

def test_fetch_bot_open_id_sync_returns_none_on_api_error() -> None:
    channel = _make_channel(bot_open_id=None)
    resp = MagicMock()
    resp.success.return_value = False
    resp.code = 99991
    channel._client.request.return_value = resp

    result = channel._fetch_bot_open_id_sync()

    assert result is None


def test_fetch_bot_open_id_sync_returns_none_on_exception() -> None:
    channel = _make_channel(bot_open_id=None)
    channel._client.request.side_effect = RuntimeError("network error")

    result = channel._fetch_bot_open_id_sync()

    assert result is None
