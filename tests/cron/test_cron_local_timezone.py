from datetime import datetime, timedelta, timezone

import pytest

from nanobot.config import timezone as timezone_config
from nanobot.cron import service
from nanobot.cron.types import CronSchedule


@pytest.mark.parametrize(
    "reference, expected, offset",
    [
        ("2026-03-08T06:30:00+00:00", "2026-03-08T13:00:00+00:00", -5),
        ("2026-11-01T04:30:00+00:00", "2026-11-01T14:00:00+00:00", -4),
    ],
)
def test_local_cron_schedule_follows_daylight_saving(monkeypatch, reference, expected, offset):
    now_ms = int(datetime.fromisoformat(reference).timestamp() * 1000)
    expected_ms = int(datetime.fromisoformat(expected).timestamp() * 1000)
    local_offset = timezone(timedelta(hours=offset))

    class LocalDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now_ms / 1000, tz=tz or local_offset)

        def astimezone(self, tz=None):
            return super().astimezone(tz or local_offset)

    monkeypatch.setattr(timezone_config, "get_localzone_name", lambda: "America/New_York")
    monkeypatch.setattr(service, "datetime", LocalDateTime)

    assert service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *", tz="America/New_York"), now_ms
    ) == expected_ms
    assert service._compute_next_run(
        CronSchedule(kind="cron", expr="0 9 * * *"), now_ms
    ) == expected_ms
