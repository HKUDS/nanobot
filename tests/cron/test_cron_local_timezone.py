from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

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
    monkeypatch.setattr(timezone_config, "get_localzone_name", lambda: "America/New_York")
    reference = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    expected = datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))

    next_run = service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"),
        int(reference.timestamp() * 1000),
    )

    assert next_run == int(expected.timestamp() * 1000)
