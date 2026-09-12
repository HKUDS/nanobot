from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from time_manager.config import Config
from time_manager.service import Service


def test_minimal_config_defaults_to_read_only_calendar_monitor(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('trigger_id = "fixture"\n', encoding="utf-8")
    config = Config.load(path)
    assert config.calendar_only is True
    assert config.auto_manage_sleep is False


@pytest.mark.parametrize("dry_run", [True, False])
def test_calendar_only_never_plans_sleep_or_wake(tmp_path, monkeypatch, dry_run):
    import time_manager.service as module
    monkeypatch.setattr(module, "scan_all", lambda *args, **kwargs: ([], []))
    def forbidden(*args, **kwargs):
        pytest.fail("calendar-only must not run sleep/wake automation")
    monkeypatch.setattr(module, "sync_sleep_blocks", forbidden)
    monkeypatch.setattr(module, "build_notices", forbidden)
    monkeypatch.setattr(module, "sleep_window", forbidden)
    service = Service(Config(calendar_only=True, auto_manage_sleep=True,
        initial_scan_notifications=True, state_path=str(tmp_path / "data/state.sqlite3")), tmp_path / "config.toml")
    try:
        assert service.scan(dry_run=dry_run)["ok"]
        assert service.scan(dry_run=dry_run)["ok"]
        assert service._sleep_plan([], datetime.now(ZoneInfo("Europe/Warsaw"))) == []
        assert not service._is_quiet(datetime.now(ZoneInfo("Europe/Warsaw")), [])
    finally:
        service.close()
