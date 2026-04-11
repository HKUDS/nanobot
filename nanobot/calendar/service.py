"""Calendar service: provider routing + scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nanobot.calendar.errors import CalendarError, CalendarErrorCode
from nanobot.calendar.providers import CalendarProvider, parse_iso_datetime
from nanobot.calendar.types import CalendarEvent, FreeSlot


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


class CalendarService:
    """High-level API on top of provider plugins."""

    def __init__(self):
        self._providers: dict[str, CalendarProvider] = {}

    def register_provider(self, provider: CalendarProvider) -> None:
        """Register provider implementation."""
        self._providers[provider.name] = provider

    def providers_status(self) -> dict[str, dict[str, Any]]:
        """Provider status map."""
        out: dict[str, dict[str, Any]] = {}
        for name, provider in self._providers.items():
            configured = provider.configured()
            item: dict[str, Any] = {
                "configured": configured,
                "status": "ready" if configured else "not_configured",
            }
            reason = getattr(provider, "reason", "")
            if reason:
                item["reason"] = reason
            out[name] = item
        return out

    def _provider(self, name: str) -> CalendarProvider:
        provider = self._providers.get(name)
        if not provider:
            raise CalendarError(
                CalendarErrorCode.UNKNOWN_PROVIDER,
                f"Unknown provider '{name}'. Available: {', '.join(self._providers.keys())}",
                details={"provider": name, "available": list(self._providers.keys())},
            )
        return provider

    def list_calendars(self, *, provider: str) -> list[dict[str, Any]]:
        """List calendars from one provider."""
        return self._provider(provider).list_calendars()

    def list_events(
        self,
        *,
        provider: str,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        """List events from one provider."""
        return self._provider(provider).list_events(
            calendar_id=calendar_id,
            start_at=start_at,
            end_at=end_at,
            attendee=attendee,
        )

    def create_event(
        self,
        *,
        provider: str,
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
        """Create event in a provider."""
        return self._provider(provider).create_event(
            calendar_id=calendar_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            description=description,
            location=location,
            attendees=attendees,
            metadata=metadata,
        )

    def update_event(
        self,
        *,
        provider: str,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        """Patch existing event."""
        return self._provider(provider).update_event(
            calendar_id=calendar_id,
            event_id=event_id,
            fields=fields,
        )

    def delete_event(self, *, provider: str, calendar_id: str | None = None, event_id: str) -> bool:
        """Delete event."""
        return self._provider(provider).delete_event(
            calendar_id=calendar_id,
            event_id=event_id,
        )

    def detect_conflicts(
        self,
        *,
        provider: str,
        calendar_id: str | None = None,
        start_at: str,
        end_at: str,
        timezone: str,
        attendees: list[str] | None = None,
        ignore_event_id: str | None = None,
    ) -> list[CalendarEvent]:
        """Find events that overlap with target interval."""
        start_dt = parse_iso_datetime(start_at, timezone)
        end_dt = parse_iso_datetime(end_at, timezone)
        if end_dt <= start_dt:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "end_at must be after start_at")

        events = self.list_events(
            provider=provider,
            calendar_id=calendar_id,
            start_at=start_dt.isoformat(),
            end_at=end_dt.isoformat(),
        )
        conflicts: list[CalendarEvent] = []
        attendee_set = set(attendees or [])
        for event in events:
            if ignore_event_id and event.id == ignore_event_id:
                continue
            event_start = parse_iso_datetime(event.start_at, event.timezone)
            event_end = parse_iso_datetime(event.end_at, event.timezone)
            if not _overlap(start_dt, end_dt, event_start, event_end):
                continue
            if attendee_set and attendee_set.isdisjoint(event.attendees):
                continue
            conflicts.append(event)
        return conflicts

    def find_free_slots(
        self,
        *,
        provider: str,
        calendar_id: str | None = None,
        start_at: str,
        end_at: str,
        timezone: str,
        duration_minutes: int,
        attendees: list[str] | None = None,
        step_minutes: int = 30,
        limit: int = 5,
    ) -> list[FreeSlot]:
        """Suggest free slots in a time range."""
        if duration_minutes <= 0:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "duration_minutes must be > 0")
        if step_minutes <= 0:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "step_minutes must be > 0")
        if limit <= 0:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "limit must be > 0")

        start_dt = parse_iso_datetime(start_at, timezone)
        end_dt = parse_iso_datetime(end_at, timezone)
        if end_dt <= start_dt:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "end_at must be after start_at")

        events = self.list_events(
            provider=provider,
            calendar_id=calendar_id,
            start_at=start_dt.isoformat(),
            end_at=end_dt.isoformat(),
        )
        attendee_set = set(attendees or [])
        busy: list[tuple[datetime, datetime]] = []
        for event in events:
            if attendee_set and attendee_set.isdisjoint(event.attendees):
                continue
            ev_start = max(start_dt, parse_iso_datetime(event.start_at, event.timezone))
            ev_end = min(end_dt, parse_iso_datetime(event.end_at, event.timezone))
            if ev_end > ev_start:
                busy.append((ev_start, ev_end))
        busy.sort(key=lambda x: x[0])

        merged: list[tuple[datetime, datetime]] = []
        for cur_start, cur_end in busy:
            if not merged:
                merged.append((cur_start, cur_end))
                continue
            last_start, last_end = merged[-1]
            if cur_start <= last_end:
                merged[-1] = (last_start, max(last_end, cur_end))
            else:
                merged.append((cur_start, cur_end))

        results: list[FreeSlot] = []
        cursor = start_dt
        required = timedelta(minutes=duration_minutes)
        step = timedelta(minutes=step_minutes)

        for block_start, block_end in merged:
            while cursor + required <= block_start and len(results) < limit:
                results.append(
                    FreeSlot(
                        start_at=cursor.isoformat(),
                        end_at=(cursor + required).isoformat(),
                        duration_minutes=duration_minutes,
                    )
                )
                cursor += step
            if cursor < block_end:
                cursor = block_end
            if len(results) >= limit:
                return results

        while cursor + required <= end_dt and len(results) < limit:
            results.append(
                FreeSlot(
                    start_at=cursor.isoformat(),
                    end_at=(cursor + required).isoformat(),
                    duration_minutes=duration_minutes,
                )
            )
            cursor += step
        return results
