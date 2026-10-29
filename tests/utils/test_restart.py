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


def test_restart_notice_drops_process_local_webui_turn_metadata(monkeypatch):
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_METADATA", raising=False)

    set_restart_notice_to_env(
        channel="websocket",
        chat_id="chat-1",
        metadata={
            "webui_turn_id": "turn-from-old-process",
            "slack": {"thread_ts": "1700.42"},
        },
    )

    notice = consume_restart_notice_from_env()
    assert notice is not None
    assert notice.metadata == {"slack": {"thread_ts": "1700.42"}}


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



async def test_restart_intent_waits_for_reply_commit_and_is_one_shot():
    from nanobot.utils.restart import RestartController

    restart = RestartController()
    ticket = restart.request()

    assert ticket is not None
    assert restart.request() is None
    assert not restart.shutdown_event.is_set()
    assert not restart.committed

    ticket.commit()
    await restart.shutdown_event.wait()
    ticket.commit()
    assert restart.committed
    assert restart.request() is None


def test_normal_shutdown_wins_over_an_undelivered_restart_reply():
    from nanobot.utils.restart import RestartController

    restart = RestartController()
    ticket = restart.request()
    assert ticket is not None
    restart.shutdown_event.set()
    ticket.commit()

    assert not restart.committed
    assert restart.request() is None


def test_standalone_restart_captures_its_launch_and_runs_only_after_unwind(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from nanobot.utils.restart import ProcessRestart, standalone_restart

    events = []
    monkeypatch.setattr("sys.argv", ["nanobot", "agent", "--classic", "--message", "/restart"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "nanobot.utils.restart.replace_process",
        lambda argv, **kwargs: events.append((argv, kwargs)),
    )

    @contextmanager
    def lease():
        try:
            yield
        finally:
            events.append("lease released")

    try:
        with lease():
            intent = standalone_restart(mode="spawn", args=["agent", "--classic", "--session", "cli:work"])
            assert events == []
            raise intent
    except ProcessRestart as restart:
        restart.execute()

    import sys

    assert events == [
        "lease released",
        ([sys.executable, "-m", "nanobot", "agent", "--classic", "--session", "cli:work"],
         {"mode": "spawn", "cwd": tmp_path}),
    ]
