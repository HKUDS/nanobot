from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from time_manager.config import Config
from time_manager.core import Event, Notice, build_notices, sleep_window
from time_manager.service import Service
from time_manager.state import State

ZONE = ZoneInfo("Europe/Warsaw")


def notices_at(now, events=()):
    return build_notices(list(events), now, default_wake=time(7), prep_minutes=90,
                         sleep_hours=8, briefing_after=20)


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
def test_sleep_duration_is_eight_real_hours_across_dst(day):
    bedtime, wake = sleep_window(day, [], ZONE, time(7), 90, 8)
    assert wake.astimezone(UTC) - bedtime.astimezone(UTC) == timedelta(hours=8)
    assert wake.hour == 7


def test_bedtime_wake_and_briefing_have_distinct_windows():
    assert "bedtime_reminder" in {n.kind for n in notices_at(datetime(2026, 9, 12, 22, 40, tzinfo=ZONE))}
    assert "wake_reminder" in {n.kind for n in notices_at(datetime(2026, 9, 12, 7, 5, tzinfo=ZONE))}
    assert "morning_briefing" in {n.kind for n in notices_at(datetime(2026, 9, 12, 7, 25, tzinfo=ZONE))}
    assert not notices_at(datetime(2026, 9, 12, 12, tzinfo=ZONE))


def test_followup_is_a_suggestion_not_an_assumption_of_attendance():
    event = Event(key="cal|1", calendar="Test", calendar_url="cal", uid="1", recurrence_id=None,
                  title="Spotkanie online", start="2026-09-12T10:00:00+02:00",
                  end="2026-09-12T11:00:00+02:00", all_day=False)
    now = datetime(2026, 9, 12, 11, 15, tzinfo=ZONE)
    followups = [n for n in notices_at(now, [event]) if n.kind == "post_event"]
    assert len(followups) == 1
    assert "nie zakładaj" in followups[0].payload["suggestion"]
    assert not [n for n in notices_at(now, [replace(event, status="CANCELLED")]) if n.kind == "post_event"]


def test_quiet_queue_promotes_urgency_and_does_not_starve_critical(tmp_path):
    state = State(tmp_path / "data" / "state.sqlite3")
    now = datetime(2026, 9, 12, 5, tzinfo=ZONE)
    try:
        for i in range(25):
            state.reserve_notice(Notice(str(i), "event_reminder", "normal", "Test", {}), now)
        state.reserve_notice(Notice("24", "event_reminder", "critical", "Urgent", {}), now)
        assert state.pending_notices(limit=1)[0].key == "24"
        assert state.pending_notices(limit=1)[0].urgency == "critical"
        state.mark_delivered("24", now)
        state.reserve_notice(Notice("24", "event_reminder", "critical", "Urgent", {}), now)
        assert "24" not in {n.key for n in state.pending_notices(limit=50)}
    finally:
        state.close()


def test_cancelled_or_outdated_reminder_expires_without_claiming_delivery(tmp_path):
    state = State(tmp_path / "data" / "state.sqlite3")
    now = datetime(2026, 9, 12, 5, tzinfo=ZONE)
    try:
        state.reserve_notice(Notice("old", "event_reminder", "normal", "Old", {}), now)
        state.reserve_notice(Notice("change", "event_changed", "high", "Change", {}), now)
        state.expire_transient_notices(set(), now)
        assert [n.key for n in state.pending_notices()] == ["change"]
        row = state.db.execute("SELECT delivered_at,expired_at FROM notices WHERE key='old'").fetchone()
        assert row["delivered_at"] is None
        assert row["expired_at"] is not None
    finally:
        state.close()


def test_sleep_plan_resyncs_after_same_day_schedule_change(tmp_path, monkeypatch):
    import time_manager.service as module

    now = datetime(2026, 9, 11, 12, tzinfo=ZONE)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(module, "datetime", Clock)
    source = []
    monkeypatch.setattr(module, "scan_all", lambda *args: (list(source), [{"name": "Test"}]))
    calls = []
    monkeypatch.setattr(module, "sync_sleep_blocks", lambda *args, **kwargs: calls.append(kwargs) or [])
    cfg = Config(state_path=str(tmp_path / "data" / "state.sqlite3"), management_calendar="Nanobot",
                 calendar_only=False, auto_manage_sleep=True)
    service = Service(cfg, tmp_path / "config.toml")
    try:
        service.scan()
        service.scan()
        assert len(calls) == 1
        source.append(Event(key="cal|1", calendar="Test", calendar_url="cal", uid="1", recurrence_id=None,
                            title="Spotkanie", start="2026-09-12T06:00:00+02:00",
                            end="2026-09-12T07:00:00+02:00", all_day=False))
        service.scan()
        assert len(calls) == 2
        service.scan()
        assert len(calls) == 2
    finally:
        service.close()


def test_dry_run_does_not_write_remote_sleep_or_enqueue(tmp_path, monkeypatch):
    import time_manager.service as module

    monkeypatch.setattr(module, "scan_all", lambda *args: ([], []))

    def forbidden(*args, **kwargs):
        raise AssertionError("dry run attempted a side effect")

    monkeypatch.setattr(module, "sync_sleep_blocks", forbidden)
    monkeypatch.setattr(Service, "_enqueue", forbidden)
    service = Service(Config(state_path=str(tmp_path / "data" / "state.sqlite3"),
                             management_calendar="Nanobot"), tmp_path / "config.toml")
    try:
        assert service.scan(dry_run=True)["dry_run"] is True
        assert not service.state.is_initialized()
    finally:
        service.close()


def test_expired_undelivered_alarm_can_become_current_again(tmp_path):
    state = State(tmp_path / "data" / "state.sqlite3")
    now = datetime(2026, 9, 12, 5, tzinfo=ZONE)
    notice = Notice("same", "event_reminder", "normal", "Test", {})
    try:
        state.reserve_notice(notice, now)
        state.expire_transient_notices(set(), now)
        assert not state.pending_notices()
        state.reserve_notice(notice, now)
        assert [n.key for n in state.pending_notices()] == ["same"]
        state.mark_delivered("same", now)
        state.expire_transient_notices(set(), now)
        state.reserve_notice(notice, now)
        assert not state.pending_notices()
    finally:
        state.close()


def test_preparation_crosses_spring_dst_in_elapsed_minutes():
    event = Event(key="cal|1", calendar="Test", calendar_url="cal", uid="1", recurrence_id=None,
                  title="Spotkanie", start="2026-03-29T03:30:00+02:00",
                  end="2026-03-29T04:00:00+02:00", all_day=False)
    _, wake = sleep_window(date(2026, 3, 29), [event], ZONE, time(7), 90, 8)
    assert event.start_dt(ZONE).astimezone(UTC) - wake.astimezone(UTC) == timedelta(minutes=90)
    assert wake.isoformat() == "2026-03-29T01:00:00+01:00"


def test_autumn_dst_does_not_make_seventy_minutes_critical():
    event = Event(key="cal|1", calendar="Test", calendar_url="cal", uid="1", recurrence_id=None,
                  title="Wizyta", start="2026-10-25T02:30:00+01:00",
                  end="2026-10-25T03:00:00+01:00", all_day=False)
    now = datetime(2026, 10, 25, 2, 20, tzinfo=ZONE, fold=0)
    reminders = [n for n in notices_at(now, [event]) if n.kind == "event_reminder"]
    assert len(reminders) == 1
    assert reminders[0].urgency == "normal"
    now_second_fold = now.replace(fold=1)
    reminders = [n for n in notices_at(now_second_fold, [event]) if n.kind == "event_reminder"]
    assert reminders[0].urgency == "critical"


def test_large_notice_batches_still_make_progress(tmp_path, monkeypatch):
    import json

    service = Service(Config(state_path=str(tmp_path / "data" / "state.sqlite3"),
                             management_calendar="Nanobot", trigger_id="test", quiet_mode="off",
                             calendar_only=False),
                      tmp_path / "config.toml")
    packets = []
    monkeypatch.setattr(service, "_enqueue", packets.append)
    now = datetime(2026, 9, 12, 12, tzinfo=ZONE)
    notices = [Notice(str(i), "conflict", "high", "Test", {"details": "x" * 5000}) for i in range(20)]
    try:
        first = service._deliver_notices(notices, now, [])
        assert 0 < first < 20
        assert len(service.state.pending_notices()) == 20 - first
        for _ in range(5):
            service._deliver_notices(notices, now, [])
        assert not service.state.pending_notices()
        assert all(len(packet) <= 48000 for packet in packets)
        delivered_keys = [n["key"] for packet in packets for n in json.loads(packet)["notices"]]
        assert len(delivered_keys) == len(set(delivered_keys)) == 20
    finally:
        service.close()


def test_single_huge_briefing_is_explicitly_bounded(tmp_path, monkeypatch):
    import json

    service = Service(Config(state_path=str(tmp_path / "data" / "state.sqlite3"),
                             management_calendar="Nanobot", trigger_id="test", quiet_mode="off",
                             calendar_only=False),
                      tmp_path / "config.toml")
    packets = []
    monkeypatch.setattr(service, "_enqueue", packets.append)
    now = datetime(2026, 9, 12, 12, tzinfo=ZONE)
    notice = Notice("briefing", "morning_briefing", "normal", "Plan", {"events": ["x" * 100000]})
    try:
        assert service._deliver_notices([notice], now, []) == 1
        assert len(packets[0]) <= 48000
        assert json.loads(packets[0])["notices"][0]["payload"]["payload_truncated"] is True
        assert not service.state.pending_notices()
    finally:
        service.close()


def test_saved_webui_credentials_are_scoped_without_mutating_environment(tmp_path, monkeypatch):
    import os

    import nanobot.integrations.credentials as store

    from time_manager.caldav_io import credentials

    monkeypatch.setenv("ICLOUD_CALDAV_USERNAME", "env-user")
    monkeypatch.setenv("ICLOUD_CALDAV_APP_PASSWORD", "env-secret")
    seen = []

    def configured(path):
        seen.append(path)
        return "ui-user", "ui-secret", "https://caldav.icloud.com/"

    monkeypatch.setattr(store, "icloud_credentials", configured)
    config_path = str(tmp_path / "config.json")
    assert credentials(config_path)[:2] == ("ui-user", "ui-secret")
    assert str(seen[0]) == config_path
    assert os.environ["ICLOUD_CALDAV_APP_PASSWORD"] == "env-secret"
    assert credentials()[:2] == ("env-user", "env-secret")


def test_service_passes_explicit_webui_config_to_caldav(tmp_path, monkeypatch):
    import time_manager.service as module

    seen = []

    def scan(*args, **kwargs):
        seen.append(kwargs)
        return [], []

    monkeypatch.setattr(module, "scan_all", scan)
    cfg_path = str(tmp_path / "nanobot.json")
    cfg = Config(state_path=str(tmp_path / "data" / "state.sqlite3"),
                 management_calendar="Nanobot", nanobot_config_path=cfg_path)
    service = Service(cfg, tmp_path / "data" / "webui.toml")
    try:
        service.check()
        service.scan(dry_run=True)
        assert seen == [{"config_path": cfg_path}, {"config_path": cfg_path}]
    finally:
        service.close()


def test_cli_never_echoes_provider_exception(monkeypatch, tmp_path, capsys):
    from time_manager import cli

    def fail(path):
        raise RuntimeError("https://user:secret@example.invalid/private-calendar")

    monkeypatch.setattr(cli.Config, "load", fail)
    assert cli.main(["--config", str(tmp_path / "fixture.toml"), "check"]) == 1
    output = capsys.readouterr().out
    assert '"error": "RuntimeError"' in output
    assert "secret" not in output and "private-calendar" not in output
