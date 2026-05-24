"""Tests for restart notice helpers."""

from __future__ import annotations

import os

from nanobot.utils.restart import (
    RestartNotice,
    consume_restart_notice_from_env,
    format_restart_completed_message,
    set_restart_notice_to_env,
    should_show_cli_restart_notice,
)


def test_set_and_consume_restart_notice_env_roundtrip(monkeypatch):
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHANNEL", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHAT_ID", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_METADATA", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_STARTED_AT", raising=False)

    set_restart_notice_to_env(channel="feishu", chat_id="oc_123")

    notice = consume_restart_notice_from_env()
    assert notice is not None
    assert notice.channel == "feishu"
    assert notice.chat_id == "oc_123"
    assert notice.started_at_raw
    assert notice.metadata == {}

    # Consumed values should be cleared from env.
    assert consume_restart_notice_from_env() is None
    assert "NANOBOT_RESTART_NOTIFY_CHANNEL" not in os.environ
    assert "NANOBOT_RESTART_NOTIFY_CHAT_ID" not in os.environ
    assert "NANOBOT_RESTART_NOTIFY_METADATA" not in os.environ
    assert "NANOBOT_RESTART_STARTED_AT" not in os.environ


def test_restart_notice_preserves_metadata_across_env(monkeypatch):
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHANNEL", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHAT_ID", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_METADATA", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_STARTED_AT", raising=False)

    set_restart_notice_to_env(
        channel="slack",
        chat_id="C123",
        metadata={"slack": {"thread_ts": "1700.42", "channel_type": "channel"}},
    )

    notice = consume_restart_notice_from_env()
    assert notice is not None
    assert notice.metadata == {
        "slack": {"thread_ts": "1700.42", "channel_type": "channel"}
    }
    assert "NANOBOT_RESTART_NOTIFY_METADATA" not in os.environ


def test_restart_notice_clears_stale_metadata(monkeypatch):
    monkeypatch.setenv("NANOBOT_RESTART_NOTIFY_METADATA", '{"stale": true}')
    set_restart_notice_to_env(channel="cli", chat_id="direct")
    assert "NANOBOT_RESTART_NOTIFY_METADATA" not in os.environ


def test_format_restart_completed_message_with_elapsed(monkeypatch):
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 102.0)
    assert format_restart_completed_message("100.0") == "Restart completed in 2.0s."


def test_should_show_cli_restart_notice():
    notice = RestartNotice(channel="cli", chat_id="direct", started_at_raw="100")
    assert should_show_cli_restart_notice(notice, "cli:direct") is True
    assert should_show_cli_restart_notice(notice, "cli:other") is False
    assert should_show_cli_restart_notice(notice, "direct") is True

    non_cli = RestartNotice(channel="feishu", chat_id="oc_1", started_at_raw="100")
    assert should_show_cli_restart_notice(non_cli, "cli:direct") is False

