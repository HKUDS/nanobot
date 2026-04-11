"""Calendar provider implementations."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


from nanobot.calendar.errors import CalendarError, CalendarErrorCode
from nanobot.calendar.types import CalendarEvent


def now_ms() -> int:
    """Current timestamp (ms)."""
    return int(time.time() * 1000)


def parse_iso_datetime(value: str, timezone: str) -> datetime:
    """Parse ISO datetime; naive input will be interpreted with provided timezone."""
    from zoneinfo import ZoneInfo

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone))
    return dt


class CalendarProvider(Protocol):
    """Provider protocol."""

    name: str

    def configured(self) -> bool:
        """Whether provider is ready for use."""
        ...

    def list_calendars(self) -> list[dict[str, Any]]:
        """List available calendars."""
        ...

    def list_events(
        self,
        *,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        """List events."""
        ...

    def get_event(self, *, calendar_id: str | None = None, event_id: str) -> CalendarEvent | None:
        """Get one event by id."""
        ...

    def create_event(
        self,
        *,
        calendar_id: str | None = None,
        title: str,
        start_at: str,
        end_at: str,
        timezone: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEvent:
        """Create an event."""
        ...

    def update_event(
        self,
        *,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        """Update an event and return updated value."""
        ...

    def delete_event(self, *, calendar_id: str | None = None, event_id: str) -> bool:
        """Delete event by id."""
        ...


class LocalCalendarProvider:
    """File-backed local calendar provider."""

    name = "local"

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._events: list[CalendarEvent] | None = None
        self._last_mtime = 0.0

    def configured(self) -> bool:
        return True

    def list_calendars(self) -> list[dict[str, Any]]:
        return [{"id": "default", "name": "Default", "is_primary": True}]

    def _load(self) -> list[CalendarEvent]:
        if self._events is not None and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                self._events = None
        if self._events is not None:
            return self._events

        if not self.store_path.exists():
            self._events = []
            return self._events
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._events = [
                CalendarEvent(
                    id=e["id"],
                    provider=e["provider"],
                    calendar_id=e.get("calendarId", "default"),
                    title=e["title"],
                    start_at=e["startAt"],
                    end_at=e["endAt"],
                    timezone=e["timezone"],
                    description=e.get("description", ""),
                    location=e.get("location", ""),
                    attendees=list(e.get("attendees", [])),
                    metadata=dict(e.get("metadata", {})),
                    created_at_ms=e.get("createdAtMs", 0),
                    updated_at_ms=e.get("updatedAtMs", 0),
                )
                for e in data.get("events", [])
            ]
        except Exception:
            self._events = []
        return self._events

    def _save(self) -> None:
        if self._events is None:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "events": [
                {
                    "id": e.id,
                    "provider": e.provider,
                    "calendarId": e.calendar_id,
                    "title": e.title,
                    "startAt": e.start_at,
                    "endAt": e.end_at,
                    "timezone": e.timezone,
                    "description": e.description,
                    "location": e.location,
                    "attendees": e.attendees,
                    "metadata": e.metadata,
                    "createdAtMs": e.created_at_ms,
                    "updatedAtMs": e.updated_at_ms,
                }
                for e in self._events
            ],
        }
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._last_mtime = self.store_path.stat().st_mtime

    def list_events(
        self,
        *,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        calendar_id = calendar_id or "default"
        events = [e for e in self._load() if e.calendar_id == calendar_id]
        if attendee:
            events = [e for e in events if attendee in e.attendees]

        if not start_at and not end_at:
            return sorted(events, key=lambda e: e.start_at)

        start_dt = parse_iso_datetime(start_at, "UTC") if start_at else None
        end_dt = parse_iso_datetime(end_at, "UTC") if end_at else None
        filtered: list[CalendarEvent] = []
        for event in events:
            event_start = parse_iso_datetime(event.start_at, event.timezone)
            event_end = parse_iso_datetime(event.end_at, event.timezone)
            if start_dt and event_end <= start_dt:
                continue
            if end_dt and event_start >= end_dt:
                continue
            filtered.append(event)
        return sorted(filtered, key=lambda e: e.start_at)

    def get_event(self, *, calendar_id: str | None = None, event_id: str) -> CalendarEvent | None:
        calendar_id = calendar_id or "default"
        for event in self._load():
            if event.calendar_id == calendar_id and event.id == event_id:
                return event
        return None

    def create_event(
        self,
        *,
        calendar_id: str | None = None,
        title: str,
        start_at: str,
        end_at: str,
        timezone: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEvent:
        calendar_id = calendar_id or "default"
        # Validate datetime range
        start_dt = parse_iso_datetime(start_at, timezone)
        end_dt = parse_iso_datetime(end_at, timezone)
        if end_dt <= start_dt:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "end_at must be after start_at")

        now = now_ms()
        event = CalendarEvent(
            id=str(uuid.uuid4())[:8],
            provider=self.name,
            calendar_id=calendar_id,
            title=title,
            start_at=start_dt.isoformat(),
            end_at=end_dt.isoformat(),
            timezone=timezone,
            description=description,
            location=location,
            attendees=list(attendees or []),
            metadata=dict(metadata or {}),
            created_at_ms=now,
            updated_at_ms=now,
        )
        events = self._load()
        events.append(event)
        self._save()
        return event

    def update_event(
        self,
        *,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        calendar_id = calendar_id or "default"
        events = self._load()
        for idx, event in enumerate(events):
            if event.calendar_id != calendar_id or event.id != event_id:
                continue
            merged = asdict(event)
            merged.update(fields)
            timezone = str(merged.get("timezone") or event.timezone)
            start_dt = parse_iso_datetime(str(merged["start_at"]), timezone)
            end_dt = parse_iso_datetime(str(merged["end_at"]), timezone)
            if end_dt <= start_dt:
                raise CalendarError(
                    CalendarErrorCode.INVALID_ARGUMENT,
                    "end_at must be after start_at",
                )

            merged["start_at"] = start_dt.isoformat()
            merged["end_at"] = end_dt.isoformat()
            merged["updated_at_ms"] = now_ms()
            merged["attendees"] = list(merged.get("attendees") or [])
            merged["metadata"] = dict(merged.get("metadata") or {})
            updated = CalendarEvent(**merged)
            events[idx] = updated
            self._save()
            return updated
        return None

    def delete_event(self, *, calendar_id: str | None = None, event_id: str) -> bool:
        calendar_id = calendar_id or "default"
        events = self._load()
        before = len(events)
        self._events = [e for e in events if not (e.calendar_id == calendar_id and e.id == event_id)]
        if len(self._events) == before:
            return False
        self._save()
        return True


class UnsupportedCalendarProvider:
    """Placeholder provider for future integrations."""

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    def configured(self) -> bool:
        return False

    def _raise(self) -> None:
        raise CalendarError(
            CalendarErrorCode.PROVIDER_NOT_CONFIGURED,
            f"Provider '{self.name}' is not configured: {self.reason}",
            details={"provider": self.name, "reason": self.reason},
        )

    def list_calendars(self) -> list[dict[str, Any]]:
        self._raise()

    def list_events(self, **kwargs: Any) -> list[CalendarEvent]:
        self._raise()

    def get_event(self, **kwargs: Any) -> CalendarEvent | None:
        self._raise()

    def create_event(self, **kwargs: Any) -> CalendarEvent:
        self._raise()

    def update_event(self, **kwargs: Any) -> CalendarEvent | None:
        self._raise()

    def delete_event(self, **kwargs: Any) -> bool:
        self._raise()


