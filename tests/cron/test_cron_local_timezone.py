from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import tzlocal

from nanobot.config import timezone as timezone_config
from nanobot.cron import service
from nanobot.cron.types import CronSchedule


@pytest.mark.parametrize(
    ("reference_month", "target_month", "offset_hours"),
    [(1, 7, -5), (7, 12, -4)],
)
def test_local_cron_preserves_wall_time_across_dst(
    monkeypatch: pytest.MonkeyPatch, reference_month: int, target_month: int, offset_hours: int
) -> None:
    local_zone = ZoneInfo("America/New_York")
    reference = datetime(2026, reference_month, 1, 12, tzinfo=local_zone)

    class LocalDateTime(datetime):
        def astimezone(self, tz=None):
            # A no-argument astimezone() exposes only the host's current offset.
            return super().astimezone(tz or timezone(timedelta(hours=offset_hours)))

    monkeypatch.setattr(service, "datetime", LocalDateTime)
    monkeypatch.setattr(timezone_config, "get_localzone_name", lambda: local_zone.key)
    monkeypatch.setattr(tzlocal, "get_localzone", lambda: local_zone)
    expression = f"0 9 1 {target_month} *"
    now_ms = int(reference.timestamp() * 1000)

    next_run = service._compute_next_run(CronSchedule(kind="cron", expr=expression), now_ms)
    explicit_run = service._compute_next_run(
        CronSchedule(kind="cron", expr=expression, tz=local_zone.key), now_ms
    )

    expected = int(datetime(2026, target_month, 1, 9, tzinfo=local_zone).timestamp() * 1000)
    assert explicit_run == expected
    assert next_run == expected


def test_explicit_cron_timezone_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable_local_zone():
        raise AssertionError("Explicit timezone must not depend on host detection")

    monkeypatch.setattr(tzlocal, "get_localzone", unavailable_local_zone)
    reference = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    expected = datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))

    next_run = service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"),
        int(reference.timestamp() * 1000),
    )

    assert next_run == int(expected.timestamp() * 1000)


def test_local_cron_preserves_system_offset_when_zone_detection_fails(monkeypatch) -> None:
    local_offset = timezone(timedelta(hours=8))

    class LocalDateTime(datetime):
        def astimezone(self, tz=None):
            return super().astimezone(tz or local_offset)

    def unavailable_local_zone():
        raise OSError("Cannot read timezone rules")

    monkeypatch.setattr(service, "datetime", LocalDateTime)
    monkeypatch.setattr(tzlocal, "get_localzone", unavailable_local_zone)
    reference = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    expected = datetime(2026, 1, 1, 9, tzinfo=local_offset)

    next_run = service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *"), int(reference.timestamp() * 1000)
    )

    assert next_run == int(expected.timestamp() * 1000)


def test_local_cron_uses_rules_without_a_discoverable_zone_name(monkeypatch) -> None:
    # Unix hosts may have /etc/localtime without any configured IANA name.
    local_zone = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(timezone_config, "get_localzone_name", lambda: None)
    monkeypatch.setattr(tzlocal, "get_localzone", lambda: local_zone)
    reference = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    expected = datetime(2026, 1, 1, 9, tzinfo=local_zone)

    next_run = service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *"), int(reference.timestamp() * 1000)
    )

    assert next_run == int(expected.timestamp() * 1000)
