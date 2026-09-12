from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from time_manager.core import Event, build_notices, classify, sleep_window
from time_manager.state import State

ZONE = ZoneInfo("Europe/Warsaw")


def event(uid: str, start: str, end: str, title: str = "Spotkanie", **kwargs) -> Event:
    return Event(key=f"cal|{uid}|master", calendar="Dom", calendar_url="cal", uid=uid, recurrence_id=None,
                 title=title, start=start, end=end, all_day=False, **kwargs)


class CoreTests(unittest.TestCase):
    def test_sleep_moves_earlier_for_morning_event(self):
        events = [event("a", "2026-09-12T07:00:00+02:00", "2026-09-12T08:00:00+02:00")]
        bedtime, wake = sleep_window(datetime(2026, 9, 12).date(), events, ZONE, time(7), 90, 8)
        self.assertEqual(wake.hour, 5)
        self.assertEqual(wake.minute, 30)
        self.assertEqual(bedtime.isoformat(), "2026-09-11T21:30:00+02:00")

    def test_conflict_is_detected(self):
        events = [
            event("a", "2026-09-12T10:00:00+02:00", "2026-09-12T11:00:00+02:00"),
            event("b", "2026-09-12T10:30:00+02:00", "2026-09-12T11:30:00+02:00"),
        ]
        notices = build_notices(events, datetime(2026, 9, 12, 8, 0, tzinfo=ZONE), default_wake=time(7), prep_minutes=90, sleep_hours=8, briefing_after=20)
        self.assertIn("conflict", [notice.kind for notice in notices])

    def test_travel_classification(self):
        self.assertEqual(classify(event("a", "2026-09-12T10:00:00+02:00", "2026-09-12T11:00:00+02:00", title="Pociąg do Gdańska")), "travel")

    def test_semantic_hash_ignores_transport_metadata(self):
        first = event("a", "2026-09-12T10:00:00+02:00", "2026-09-12T11:00:00+02:00", source_url="https://old")
        second = Event(**{**first.__dict__, "source_url": "https://new", "last_modified": "2026-09-11T12:00:00Z", "sequence": 3})
        self.assertEqual(first.hash(), second.hash())

    def test_state_reconcile_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            now = datetime(2026, 9, 11, 12, tzinfo=ZONE)
            value = event("a", "2026-09-12T10:00:00+02:00", "2026-09-12T11:00:00+02:00")
            created, changed, removed = state.reconcile([value], now, now, datetime(2026, 9, 20, tzinfo=ZONE))
            self.assertEqual((len(created), len(changed), len(removed)), (1, 0, 0))
            created, changed, removed = state.reconcile([value], now.replace(minute=5), now, datetime(2026, 9, 20, tzinfo=ZONE))
            self.assertEqual((len(created), len(changed), len(removed)), (0, 0, 0))
            state.close()

    def test_removal_requires_three_complete_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            now = datetime(2026, 9, 11, 12, tzinfo=ZONE)
            end = datetime(2026, 9, 20, tzinfo=ZONE)
            value = event("a", "2026-09-12T10:00:00+02:00", "2026-09-12T11:00:00+02:00")
            state.reconcile([value], now, now, end)
            for minute in (5, 10):
                _, _, removed = state.reconcile([], now.replace(minute=minute), now, end)
                self.assertEqual(removed, [])
            _, _, removed = state.reconcile([], now.replace(minute=15), now, end)
            self.assertEqual([item.uid for item in removed], ["a"])
            state.close()


if __name__ == "__main__":
    unittest.main()
