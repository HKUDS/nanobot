"""Calendar tool for unified event management."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.calendar.errors import CalendarError, CalendarErrorCode
from nanobot.calendar.providers import (
    LocalCalendarProvider,
)
from nanobot.calendar.service import CalendarService


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return "Error: " + _json(payload)


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Action",
            enum=[
                "providers",
                "create",
                "list",
                "list_calendars",
                "update",
                "delete",
                "conflicts",
                "find_free_slots",
            ],
        ),
        provider=StringSchema("Provider name: local", nullable=True),
        calendar_id=StringSchema("Calendar identifier", nullable=True),
        event_id=StringSchema("Event ID for update/delete", nullable=True),
        title=StringSchema("Event title", nullable=True),
        event_description=StringSchema("Event description", nullable=True),
        location=StringSchema("Event location", nullable=True),
        start_at=StringSchema("ISO datetime start (e.g. 2026-04-12T09:00:00+08:00)", nullable=True),
        end_at=StringSchema("ISO datetime end (e.g. 2026-04-12T10:00:00+08:00)", nullable=True),
        timezone=StringSchema("IANA timezone, e.g. Asia/Shanghai", nullable=True),
        attendee=StringSchema("Single attendee filter for list", nullable=True),
        attendees=ArraySchema(StringSchema("Attendee"), nullable=True),
        metadata=ObjectSchema(
            description="Event metadata object",
            nullable=True,
            additional_properties=True,
        ),
        updates=ObjectSchema(
            description="Fields for update action (title/start_at/end_at/description/location/timezone/attendees/metadata)",
            nullable=True,
            additional_properties=True,
        ),
        duration_minutes=IntegerSchema(description="Duration for find_free_slots", nullable=True, minimum=1),
        step_minutes=IntegerSchema(description="Step size for find_free_slots", nullable=True, minimum=1),
        limit=IntegerSchema(description="Max number of slots", nullable=True, minimum=1, maximum=20),
        ignore_event_id=StringSchema("Event id to ignore during conflict checks", nullable=True),
        required=["action"],
    )
)
class CalendarTool(Tool):
    """Manage calendar events via unified provider APIs."""

    def __init__(self, workspace: Path, default_timezone: str = "UTC"):
        self.default_timezone = default_timezone
        store_path = workspace / ".nanobot" / "calendar" / "events.json"
        self.service = CalendarService()
        self.service.register_provider(LocalCalendarProvider(store_path))

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return (
            "Manage calendar events with a unified model. "
            "Actions: providers, list_calendars, create, list, update, delete, conflicts, find_free_slots."
        )

    async def execute(
        self,
        action: str,
        provider: str | None = None,
        calendar_id: str | None = None,
        event_id: str | None = None,
        title: str | None = None,
        event_description: str | None = None,
        location: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        timezone: str | None = None,
        attendee: str | None = None,
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
        duration_minutes: int | None = None,
        step_minutes: int | None = None,
        limit: int | None = None,
        ignore_event_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        provider = provider or "local"
        timezone = timezone or self.default_timezone

        try:
            if action == "providers":
                return _json(self.service.providers_status())

            if action == "list_calendars":
                calendars = self.service.list_calendars(provider=provider)
                return _json({"calendars": calendars})

            if action == "create":
                if not title:
                    return _error(CalendarErrorCode.INVALID_ARGUMENT, "title is required for create")
                if not start_at or not end_at:
                    return _error(
                        CalendarErrorCode.INVALID_ARGUMENT,
                        "start_at and end_at are required for create",
                    )
                event = self.service.create_event(
                    provider=provider,
                    calendar_id=calendar_id,
                    title=title,
                    start_at=start_at,
                    end_at=end_at,
                    timezone=timezone,
                    description=event_description or "",
                    location=location or "",
                    attendees=attendees or [],
                    metadata=metadata or {},
                )
                return _json({"event": asdict(event)})

            if action == "list":
                events = self.service.list_events(
                    provider=provider,
                    calendar_id=calendar_id,
                    start_at=start_at,
                    end_at=end_at,
                    attendee=attendee,
                )
                return _json({"events": [asdict(e) for e in events]})

            if action == "update":
                if not event_id:
                    return _error(CalendarErrorCode.INVALID_ARGUMENT, "event_id is required for update")
                if not updates:
                    return _error(CalendarErrorCode.INVALID_ARGUMENT, "updates is required for update")
                normalized = dict(updates)
                allowed_update_fields = {
                    "title",
                    "start_at",
                    "end_at",
                    "description",
                    "location",
                    "timezone",
                    "attendees",
                    "metadata",
                }
                unknown_fields = sorted(set(normalized.keys()) - allowed_update_fields)
                if unknown_fields:
                    return _error(
                        CalendarErrorCode.INVALID_ARGUMENT,
                        "updates contains unsupported fields",
                        {"unknown_fields": unknown_fields},
                    )
                if "attendees" in normalized and normalized["attendees"] is not None:
                    normalized["attendees"] = list(normalized["attendees"])
                if "metadata" in normalized and normalized["metadata"] is not None:
                    normalized["metadata"] = dict(normalized["metadata"])
                event = self.service.update_event(
                    provider=provider,
                    calendar_id=calendar_id,
                    event_id=event_id,
                    fields=normalized,
                )
                if not event:
                    return _error(
                        CalendarErrorCode.NOT_FOUND,
                        f"event '{event_id}' not found",
                        {"event_id": event_id},
                    )
                return _json({"event": asdict(event)})

            if action == "delete":
                if not event_id:
                    return _error(CalendarErrorCode.INVALID_ARGUMENT, "event_id is required for delete")
                ok = self.service.delete_event(
                    provider=provider,
                    calendar_id=calendar_id,
                    event_id=event_id,
                )
                if not ok:
                    return _error(
                        CalendarErrorCode.NOT_FOUND,
                        f"event '{event_id}' not found",
                        {"event_id": event_id},
                    )
                return _json({"deleted": True, "event_id": event_id})

            if action == "conflicts":
                if not start_at or not end_at:
                    return _error(
                        CalendarErrorCode.INVALID_ARGUMENT,
                        "start_at and end_at are required for conflicts",
                    )
                conflicts = self.service.detect_conflicts(
                    provider=provider,
                    calendar_id=calendar_id,
                    start_at=start_at,
                    end_at=end_at,
                    timezone=timezone,
                    attendees=attendees,
                    ignore_event_id=ignore_event_id,
                )
                return _json({"conflicts": [asdict(e) for e in conflicts]})

            if action == "find_free_slots":
                if not start_at or not end_at:
                    return _error(
                        CalendarErrorCode.INVALID_ARGUMENT,
                        "start_at and end_at are required for find_free_slots",
                    )
                if not duration_minutes:
                    return _error(
                        CalendarErrorCode.INVALID_ARGUMENT,
                        "duration_minutes is required for find_free_slots",
                    )
                slots = self.service.find_free_slots(
                    provider=provider,
                    calendar_id=calendar_id,
                    start_at=start_at,
                    end_at=end_at,
                    timezone=timezone,
                    duration_minutes=duration_minutes,
                    attendees=attendees,
                    step_minutes=step_minutes or 30,
                    limit=limit or 5,
                )
                return _json({"slots": [asdict(slot) for slot in slots]})

            return _error(
                CalendarErrorCode.INVALID_ARGUMENT,
                f"unknown action '{action}'",
                {"action": action},
            )
        except CalendarError as e:
            return _error(e.code, e.message, e.details)
        except ValueError as e:
            return _error(CalendarErrorCode.INVALID_ARGUMENT, str(e))
        except Exception as e:
            return _error(CalendarErrorCode.PROVIDER_UNAVAILABLE, str(e))
