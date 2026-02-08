from typing import Any, TYPE_CHECKING
from nanobot.agent.tools.base import Tool
from nanobot.providers.calendar import CalendarProvider, CalendarEvent

if TYPE_CHECKING:
    from nanobot.config.schema import GoogleCalendarConfig

class CalendarTool(Tool):
    """Tool for interacting with a Calendar provider."""

    name = "calendar"
    description = "Manage calendar events (list, create)."

    def __init__(self, provider: CalendarProvider):
        self.provider = provider

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "list_calendars"],
                    "description": "Action: 'list' (events), 'create' (event), or 'list_calendars'."
                },
                "calendar_id": {"type": "string", "default": "all", "description": "Calendar ID"},
                "max_results": {"type": "integer", "default": 10},
                "summary": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time ISO"},
                "end_time": {"type": "string", "description": "End time ISO"},
                "description": {"type": "string"}
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        try:
            if action == "list_calendars":
                calendars = await self.provider.list_calendars()
                if not calendars:
                    return "No calendars found."
                return "Available Calendars:\n" + "\n".join(
                    f"- {c.summary} (ID: {c.id})" for c in calendars
                )
                
            elif action == "list":
                events = await self.provider.list_events(
                    kwargs.get("max_results", 10), 
                    kwargs.get("calendar_id", "all")
                )
                if not events:
                    return "No upcoming events found."

                lines = ["Upcoming events:"]
                for e in events:
                    ctx = f" [{e.calendar_summary}]" if e.calendar_summary else ""
                    lines.append(f"- {e.start}{ctx}: {e.summary}")
                return "\n".join(lines)
                
            elif action == "create":
                required = ["summary", "start_time", "end_time"]
                if not all(kwargs.get(k) for k in required):
                    return f"Missing required parameters: {', '.join(required)}"
                    
                link = await self.provider.create_event(CalendarEvent(
                    summary=kwargs["summary"],
                    start=kwargs["start_time"],
                    end=kwargs["end_time"],
                    description=kwargs.get("description"),
                    calendar_id=kwargs.get("calendar_id", "primary")
                ))
                return f"Event created: {link}"
                
            return f"Unknown action: {action}"
                
        except Exception as e:
            return f"Error executing Calendar action: {str(e)}"
