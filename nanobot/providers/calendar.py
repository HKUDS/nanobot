"""Calendar provider interface."""

import datetime
import os.path
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
    from nanobot.config.schema import GoogleCalendarConfig


@dataclass
class CalendarEvent:
    """A calendar event."""
    summary: str
    start: str
    end: str
    description: str | None = None
    html_link: str | None = None
    calendar_id: str = "primary"
    calendar_summary: str | None = None


@dataclass
class CalendarInfo:
    """Information about a calendar."""
    id: str
    summary: str
    primary: bool = False
    selected: bool = False


class CalendarProvider(ABC):
    """Abstract base class for calendar providers."""

    @abstractmethod
    async def list_events(self, max_results: int = 10, calendar_id: str = "all") -> list[CalendarEvent]:
        """List upcoming events."""
        pass

    @abstractmethod
    async def create_event(self, event: CalendarEvent) -> str:
        """Create a new event. Returns the HTML link or confirmation string."""
        pass

    @abstractmethod
    async def list_calendars(self) -> list[CalendarInfo]:
        """List available calendars."""
        pass


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar provider implementation."""
    
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, config: "GoogleCalendarConfig"):
        self.config = config
        self._service = None

    def _get_credentials(self) -> Optional["Credentials"]:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        
        token_path = os.path.expanduser(self.config.token_path)
        creds = None
        
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(token_path, "w") as token:
                        token.write(creds.to_json())
                except Exception:
                    return None
            else:
                return None
        
        return creds

    def _get_service(self):
        if self._service:
            return self._service
            
        creds = self._get_credentials()
        if not creds:
            raise ValueError("Authentication required. Please run 'nanobot calendar auth' first.")
            
        from googleapiclient.discovery import build
        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    async def list_calendars(self) -> list[CalendarInfo]:
        service = self._get_service()
        # simplified: no try/except needed if we just let exceptions bubble up
        result = service.calendarList().list().execute()
        return [
            CalendarInfo(
                id=item["id"],
                summary=item.get("summary", "Unknown"),
                primary=item.get("primary", False),
                selected=item.get("selected", False)
            )
            for item in result.get("items", [])
        ]

    async def list_events(self, max_results: int = 10, calendar_id: str = "all") -> list[CalendarEvent]:
        service = self._get_service()
        now = datetime.datetime.now().astimezone().isoformat()
        
        if calendar_id == "all":
            calendars = service.calendarList().list().execute().get("items", [])
            # Filter for selected/primary only
            calendars = [c for c in calendars if c.get("selected") or c.get("primary")]
        else:
            calendars = [service.calendars().get(calendarId=calendar_id).execute()]

        all_events = []
        for cal in calendars:
            try:
                events = service.events().list(
                    calendarId=cal["id"], timeMin=now,
                    maxResults=max_results, singleEvents=True,
                    orderBy="startTime"
                ).execute().get("items", [])
                
                for item in events:
                    item["_calendar_summary"] = cal.get("summary", "Unknown")
                    all_events.append(item)
            except Exception:
                continue

        # Sort and limit
        def get_start(e):
            return e["start"].get("dateTime", e["start"].get("date"))
            
        all_events.sort(key=get_start)
        
        return [
            CalendarEvent(
                summary=e.get("summary", "(No Title)"),
                start=get_start(e),
                end=e["end"].get("dateTime", e["end"].get("date")),
                description=e.get("description"),
                html_link=e.get("htmlLink"),
                calendar_summary=e.get("_calendar_summary")
            )
            for e in all_events[:max_results]
        ]

    async def create_event(self, event: CalendarEvent) -> str:
        service = self._get_service()
        created = service.events().insert(
            calendarId=event.calendar_id, 
            body={
                "summary": event.summary,
                "description": event.description,
                "start": {"dateTime": event.start}, 
                "end": {"dateTime": event.end},
            }
        ).execute()
        return created.get('htmlLink', "Event created")
