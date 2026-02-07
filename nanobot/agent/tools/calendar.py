import datetime
import os.path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from googleapiclient.discovery import build

from nanobot.agent.tools.base import Tool
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.config.schema import GoogleCalendarConfig

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarTool(Tool):
    """Tool for interacting with Google Calendar."""

    name = "google_calendar"
    description = "Manage Google Calendar events (list, create)."

    def __init__(self, config: "GoogleCalendarConfig"):
        self.config = config

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "list_calendars"],
                    "description": "Action to perform: 'list' (events), 'create' (event), or 'list_calendars'."
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to interact with. Default: 'all' for list (aggregates all), 'primary' for create.",
                    "default": "all"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of events to list (for 'list' action). Default 10.",
                    "default": 10
                },
                "summary": {
                    "type": "string",
                    "description": "Title of the event (for 'create' action)."
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in ISO format (e.g. '2023-10-27T10:00:00') (for 'create' action)."
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in ISO format (for 'create' action)."
                },
                "description": {
                    "type": "string",
                    "description": "Description of the event (for 'create' action)."
                }
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs: Any) -> str:
        if not self.config.enabled:
            return "Google Calendar tool is disabled in configuration."

        action = kwargs.get("action")
        if not action:
            return "Missing required parameter: 'action'."
        creds = self._get_credentials()
        if not creds:
            return (
                f"Authentication required. Please:\n"
                f"1. Place the OAuth client secrets JSON (downloaded from Google Cloud Console) at {self.config.credentials_path}\n"
                f"2. Run the setup script to generate the token (or ensure 'token.json' exists at {self.config.token_path})."
            )

        try:
            service = build("calendar", "v3", credentials=creds)

            if action == "list_calendars":
                return self._list_calendars(service)
            elif action == "list":
                calendar_id = kwargs.get("calendar_id", "all")
                return self._list_events(service, kwargs.get("max_results", 10), calendar_id)
            elif action == "create":
                summary = kwargs.get("summary")
                start = kwargs.get("start_time")
                end = kwargs.get("end_time")
                desc = kwargs.get("description")
                calendar_id = kwargs.get("calendar_id", "primary")
                if not all([summary, start, end]):
                    return "Missing required parameters for 'create': summary, start_time, end_time."
                return self._create_event(service, calendar_id, summary, start, end, desc)
            else:
                return f"Unknown action: {action}"

        except Exception as e:
            return f"Error executing Google Calendar action: {str(e)}"

    def _get_credentials(self) -> Optional[Credentials]:
        creds = None
        token_path = os.path.expanduser(self.config.token_path)
        
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # Save the credentials for the next run
                    with open(token_path, "w") as token:
                        token.write(creds.to_json())
                except Exception:
                    # Refresh failed
                    return None
            else:
                # No valid token and no way to refresh automatically
                return None
        
        return creds

    def _list_calendars(self, service):
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])
        
        if not calendars:
            return "No calendars found."
            
        result = "Available Calendars:\n"
        for cal in calendars:
            result += f"- {cal['summary']} (ID: {cal['id']})\n"
        return result

    def _list_events(self, service, max_results, calendar_id="all"):
        # Use local time with timezone offset for API compatibility
        now = datetime.datetime.now().astimezone().isoformat()
        
        target_calendars = []
        
        if calendar_id == "all":
            # Get all calendars
            calendars_result = service.calendarList().list().execute()
            target_calendars = calendars_result.get("items", [])
        else:
            # Just specific one, use a dummy object with id
            # We fetch summary if possible, but for simplicity just use ID if single
            try:
                cal_meta = service.calendars().get(calendarId=calendar_id).execute()
                target_calendars = [cal_meta]
            except Exception:
                return f"Error: Calendar ID '{calendar_id}' not found."

        all_events = []
        
        # Fetch events from each calendar
        for calendar in target_calendars:
            cal_id = calendar["id"]
            cal_summary = calendar.get("summary", "Unknown")
            
            # Skip unselected only if iterating all
            if calendar_id == "all":
                if not calendar.get("selected", False) and not calendar.get("primary", False):
                     continue

            try:
                events_result = service.events().list(
                    calendarId=cal_id, timeMin=now,
                    maxResults=max_results, singleEvents=True,
                    orderBy="startTime"
                ).execute()
                items = events_result.get("items", [])
                
                for item in items:
                    item["_calendar_summary"] = cal_summary
                    all_events.append(item)
            except Exception:
                continue

        if not all_events:
            return "No upcoming events found."

        # Sort aggregated events by start time
        def get_start(e):
            return e["start"].get("dateTime", e["start"].get("date"))
            
        all_events.sort(key=get_start)
        all_events = all_events[:max_results]

        result = "Upcoming events:\n"
        for event in all_events:
            start = get_start(event)
            cal_name = event["_calendar_summary"]
            summary = event.get("summary", "(No Title)")
            result += f"- {start} [{cal_name}]: {summary}\n"
        return result

    def _create_event(self, service, calendar_id, summary, start_time, end_time, description):
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time}, 
            "end": {"dateTime": end_time},
        }
        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        return f"Event created: {event.get('htmlLink')}"
