from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Event:
    key: str
    calendar: str
    calendar_url: str
    uid: str
    recurrence_id: str | None
    title: str
    start: str
    end: str | None
    all_day: bool
    location: str | None = None
    description: str | None = None
    status: str | None = None
    transparency: str | None = None
    organizer: str | None = None
    attendees: tuple[str, ...] = field(default_factory=tuple)
    categories: tuple[str, ...] = field(default_factory=tuple)
    sequence: int = 0
    last_modified: str | None = None
    source_url: str | None = None

    def hash(self) -> str:
        """Hash tylko semantyki użytkowej; pomija niestabilne metadane transportowe."""
        semantic = {
            "uid": self.uid, "recurrence_id": self.recurrence_id, "title": self.title,
            "start": self.start, "end": self.end, "all_day": self.all_day,
            "location": self.location, "description": self.description, "status": self.status,
            "transparency": self.transparency, "organizer": self.organizer,
            "attendees": sorted(self.attendees), "categories": sorted(self.categories),
        }
        body = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()

    def start_dt(self, zone: ZoneInfo) -> datetime:
        value = datetime.fromisoformat(self.start)
        return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)

    def end_dt(self, zone: ZoneInfo) -> datetime:
        if self.end:
            value = datetime.fromisoformat(self.end)
            return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
        return self.start_dt(zone) + (timedelta(days=1) if self.all_day else timedelta(hours=1))


@dataclass(frozen=True)
class Notice:
    key: str
    kind: str
    urgency: str
    title: str
    payload: dict[str, Any]


PHYSICAL_WORDS = re.compile(r"\b(lekarz|dentyst|urząd|wizyta|lot|pociąg|wyjazd|spotkanie|szkoł|uczeln|trening|kino|restaurac)\w*", re.I)
TRAVEL_WORDS = re.compile(r"\b(lot|samolot|pociąg|dworzec|lotnisko|hotel|wyjazd|podróż)\w*", re.I)
BIRTHDAY_WORDS = re.compile(r"\b(urodziny|rocznica|imieniny)\b", re.I)
ONLINE_WORDS = re.compile(r"\b(zoom|teams|meet|webex|online|https?://)\b", re.I)


def classify(event: Event) -> str:
    text = " ".join(filter(None, (event.title, event.location, event.description)))
    if TRAVEL_WORDS.search(text):
        return "travel"
    if BIRTHDAY_WORDS.search(text):
        return "birthday"
    if ONLINE_WORDS.search(text) and not (event.location and not ONLINE_WORDS.search(event.location)):
        return "online"
    if PHYSICAL_WORDS.search(text):
        return "physical"
    return "general"


def is_managed(event: Event) -> bool:
    return event.uid.startswith("nanobot-sleep-") or "NANOBOT" in {item.upper() for item in event.categories}


def canonical_events(events: Iterable[Event]) -> list[Event]:
    """Deduplikuj analitycznie kopie tego samego globalnego wydarzenia."""
    result: dict[tuple[str, str, str, str], Event] = {}
    for event in events:
        identity = (event.uid or event.key, event.recurrence_id or "", event.start, event.end or "")
        result.setdefault(identity, event)
    return list(result.values())


def wake_for_day(day: date, events: Iterable[Event], zone: ZoneInfo, default_wake: time, prep_minutes: int) -> datetime:
    default = datetime.combine(day, default_wake, zone)
    candidates = []
    for event in canonical_events(events):
        if (event.all_day or (event.status or "").upper() == "CANCELLED"
                or (event.transparency or "").upper() == "TRANSPARENT" or is_managed(event)):
            continue
        start = event.start_dt(zone)
        if start.date() != day:
            continue
        candidates.append((start.astimezone(UTC) - timedelta(minutes=prep_minutes)).astimezone(zone))
    return min([default, *candidates], key=lambda value: value.timestamp()) if candidates else default


def sleep_window(day: date, events: Iterable[Event], zone: ZoneInfo, default_wake: time, prep_minutes: int, sleep_hours: float) -> tuple[datetime, datetime]:
    wake = wake_for_day(day, events, zone, default_wake, prep_minutes)
    # Subtract elapsed time, not wall-clock time, across DST transitions.
    bedtime = (wake.astimezone(UTC) - timedelta(hours=sleep_hours)).astimezone(zone)
    return bedtime, wake


def build_notices(events: list[Event], now: datetime, *, default_wake: time, prep_minutes: int, sleep_hours: float, briefing_after: int) -> list[Notice]:
    zone = now.tzinfo
    assert isinstance(zone, ZoneInfo)
    active = canonical_events(e for e in events if (e.status or "").upper() != "CANCELLED" and not is_managed(e))
    notices: list[Notice] = []

    horizon = now + timedelta(days=14)
    timed = sorted((e for e in active if not e.all_day and (e.transparency or "").upper() != "TRANSPARENT" and now - timedelta(hours=1) <= e.start_dt(zone) <= horizon), key=lambda e: e.start_dt(zone))
    open_events: list[Event] = []
    for current in timed:
        open_events = [item for item in open_events if item.end_dt(zone) > current.start_dt(zone)]
        for other in open_events:
            pair = "|".join(sorted((other.key, current.key)))
            notices.append(Notice(
                key=f"conflict:{hashlib.sha256(pair.encode()).hexdigest()[:20]}", kind="conflict", urgency="high",
                title="Konflikt w kalendarzu", payload={"events": [public_event(other), public_event(current)]},
            ))
        open_events.append(current)

    for event in active:
        category = classify(event)
        if event.all_day:
            if category == "birthday":
                event_day = date.fromisoformat(event.start)
                days = (event_day - now.date()).days
                if 0 <= days <= 3:
                    notices.append(Notice(
                        key=f"reminder:{event.key}:birthday:{event.start}", kind="event_reminder", urgency="normal",
                        title=f"Nadchodzące: {event.title}", payload={"category": category, "event": public_event(event)},
                    ))
            continue
        start = event.start_dt(zone)
        delta = start.astimezone(UTC) - now.astimezone(UTC)
        lead = {"travel": timedelta(hours=24), "birthday": timedelta(days=3), "physical": timedelta(hours=2), "online": timedelta(minutes=15)}.get(category, timedelta(minutes=30))
        if timedelta(minutes=-10) <= delta <= lead:
            bucket = {"travel": "24h", "birthday": "3d", "physical": "2h", "online": "15m"}.get(category, "30m")
            notices.append(Notice(
                key=f"reminder:{event.key}:{bucket}:{start.isoformat()}", kind="event_reminder",
                urgency="critical" if delta <= timedelta(minutes=15) else "normal",
                title=f"Nadchodzące: {event.title}", payload={"category": category, "event": public_event(event)},
            ))
        ended = now.astimezone(UTC) - event.end_dt(zone).astimezone(UTC)
        if category in {"physical", "online", "travel"} and timedelta(minutes=10) <= ended < timedelta(minutes=40):
            notices.append(Notice(
                key=f"followup:{event.key}:{event.hash()}", kind="post_event", urgency="normal",
                title=f"Po wydarzeniu: {event.title}",
                payload={"event": public_event(event), "suggestion": "Sprawdź, czy zostały ustalenia lub kolejne działania; nie zakładaj, że wydarzenie się odbyło."},
            ))
        if category in {"physical", "travel"} and not (event.location or "").strip() and timedelta(0) < delta <= timedelta(hours=48):
            notices.append(Notice(
                key=f"missing-location:{event.key}:{start.isoformat()}", kind="missing_information", urgency="normal",
                title=f"Brak lokalizacji: {event.title}", payload={"event": public_event(event)},
            ))

    for offset in (0, 1):
        wake_day = now.date() + timedelta(days=offset)
        bedtime, planned_wake = sleep_window(wake_day, active, zone, default_wake, prep_minutes, sleep_hours)
        if bedtime.astimezone(UTC) - timedelta(minutes=30) <= now.astimezone(UTC) < bedtime.astimezone(UTC):
            notices.append(Notice(
                key=f"bedtime:{wake_day.isoformat()}:{bedtime.isoformat()}", kind="bedtime_reminder",
                urgency="normal", title="Przygotuj się do snu",
                payload={"bedtime": bedtime.isoformat(), "wake": planned_wake.isoformat()},
            ))
        if planned_wake.astimezone(UTC) <= now.astimezone(UTC) < planned_wake.astimezone(UTC) + timedelta(minutes=15):
            notices.append(Notice(
                key=f"wake:{wake_day.isoformat()}:{planned_wake.isoformat()}", kind="wake_reminder",
                urgency="normal", title="Planowana pora pobudki",
                payload={"wake": planned_wake.isoformat()},
            ))
    wake = wake_for_day(now.date(), active, zone, default_wake, prep_minutes)
    briefing_at = wake.astimezone(UTC) + timedelta(minutes=briefing_after)
    if briefing_at <= now.astimezone(UTC) < briefing_at + timedelta(minutes=30):
        day_start = datetime.combine(now.date(), time.min, zone)
        day_end = day_start + timedelta(days=1)
        today = [public_event(e) for e in active if e.start_dt(zone) < day_end and e.end_dt(zone) > day_start]
        notices.append(Notice(
            key=f"briefing:{now.date().isoformat()}", kind="morning_briefing", urgency="normal",
            title="Briefing poranny", payload={"date": now.date().isoformat(), "wake": wake.isoformat(), "events": today},
        ))
    return notices


def _bounded(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    clean = "".join(char for char in str(value) if char in "\n\t" or ord(char) >= 32)
    return clean[:limit] + ("…" if len(clean) > limit else "")


def public_event(event: Event) -> dict[str, Any]:
    return {
        "calendar": _bounded(event.calendar, 120), "uid": _bounded(event.uid, 200),
        "title": _bounded(event.title, 300), "start": event.start, "end": event.end,
        "all_day": event.all_day, "location": _bounded(event.location, 300),
        "status": event.status, "attendee_count": len(event.attendees),
        "description_excerpt": _bounded(event.description, 600),
    }


def parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Nieprawidłowa godzina: {value}") from exc
