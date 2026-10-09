"""Tests for the Feishu bot-to-bot allowlist and hop guard."""

from nanobot.channels.feishu.bot_senders import BotHopGuard, bot_sender_allowed


def test_bot_sender_allowed_defaults_to_deny() -> None:
    assert bot_sender_allowed("ou_peer", []) is False
    assert bot_sender_allowed("", ["ou_peer"]) is False
    assert bot_sender_allowed("ou_peer", None) is False


def test_bot_sender_allowed_list_and_wildcard() -> None:
    assert bot_sender_allowed("ou_peer", ["ou_peer"]) is True
    assert bot_sender_allowed("ou_other", ["ou_peer"]) is False
    assert bot_sender_allowed("ou_other", ["*"]) is True
    assert bot_sender_allowed("ou_peer", ["  ou_peer  "]) is True


def test_hop_guard_caps_consecutive_bot_turns_and_tracks_peer() -> None:
    guard = BotHopGuard(limit=2)
    assert guard.accept("oc_chat", "ou_peer") is True
    assert guard.pending_peer("oc_chat") == "ou_peer"
    assert guard.accept("oc_chat", "ou_peer") is True
    assert guard.accept("oc_chat", "ou_peer") is False
    assert guard.consume_peer("oc_chat") == "ou_peer"
    assert guard.pending_peer("oc_chat") is None


def test_human_message_resets_hop_budget() -> None:
    guard = BotHopGuard(limit=1)
    assert guard.accept("oc_chat", "ou_peer") is True
    assert guard.accept("oc_chat", "ou_peer") is False
    guard.human_message("oc_chat")
    assert guard.accept("oc_chat", "ou_peer") is True


def test_zero_limit_disables_the_cap() -> None:
    guard = BotHopGuard(limit=0)
    for _ in range(5):
        assert guard.accept("oc_chat", "ou_peer") is True
