---
name: calendar
description: "Google Calendar integration via Apps Script API. Use when checking schedule, meetings, today's events, weekly calendar, or adding events."
---
# Google Calendar Integration

> **First time?** If `setup_complete: false` above, run `./SETUP.md` first, then set `setup_complete: true`.

Check and manage calendar events via Google Apps Script API.

## Workflow

1. **Check availability** - Query today/week/upcoming events
2. **Create events** - Add with title, time, description, guests
3. **Send invites** - Use `guests` param to auto-send calendar invites

## API Actions

| Action | Description | Params |
|--------|-------------|--------|
| `today` | Today's events | - |
| `week` | This week's events | - |
| `upcoming` | Next N hours | `hours` (default: 4) |
| `range` | Date range | `start`, `end` (ISO dates) |
| `create` | Create event | `title`, `start`, `end`, `guests`, `description`, `location` |

## Examples

```bash
# Today's events
curl "$URL?action=today&token=$TOKEN"

# Create meeting with guest invite
curl "$URL?action=create&title=Meeting&start=2026-01-15T10:00:00&end=2026-01-15T11:00:00&guests=email@example.com&token=$TOKEN"
```

## Response Format

```json
{
  "count": 1,
  "events": [
    {
      "title": "Meeting Name",
      "start": "2026-01-04T09:00:00.000Z",
      "end": "2026-01-04T10:00:00.000Z",
      "location": "Zoom link or address",
      "isAllDay": false
    }
  ]
}
```

## Integration

Works with other skills:
- **zoom-meeting** - Check conflicts before scheduling
- **whatsapp** - Notify contacts about calendar invites
