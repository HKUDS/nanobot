/**
 * Google Calendar API - Apps Script
 *
 * Deploy as Web App with access: "Anyone"
 * Execute as: "Me" (your account)
 */

// Configuration - set your secret token
const AUTH_TOKEN = 'YOUR_SECRET_TOKEN_HERE';

function doGet(e) {
  // Verify token
  const token = e.parameter.token;
  if (token !== AUTH_TOKEN) {
    return jsonResponse({ error: 'Unauthorized' }, 401);
  }

  const action = e.parameter.action || 'today';

  try {
    let events;

    switch (action) {
      case 'today':
        events = getTodayEvents();
        break;
      case 'week':
        events = getWeekEvents();
        break;
      case 'upcoming':
        const hours = parseInt(e.parameter.hours) || 4;
        events = getUpcomingEvents(hours);
        break;
      case 'range':
        const start = e.parameter.start;
        const end = e.parameter.end;
        if (!start || !end) {
          return jsonResponse({ error: 'Missing start or end parameter' }, 400);
        }
        events = getRangeEvents(new Date(start), new Date(end));
        break;
      case 'add':
        const title = e.parameter.title;
        const startTime = e.parameter.startTime;
        const endTime = e.parameter.endTime;
        const description = e.parameter.description || '';
        if (!title || !startTime || !endTime) {
          return jsonResponse({ error: 'Missing title, startTime or endTime' }, 400);
        }
        const newEvent = addEvent(title, new Date(startTime), new Date(endTime), description);
        return jsonResponse({ success: true, event: newEvent });
      default:
        return jsonResponse({ error: 'Unknown action' }, 400);
    }

    return jsonResponse({
      count: events.length,
      events: events
    });

  } catch (error) {
    return jsonResponse({ error: error.toString() }, 500);
  }
}

function getTodayEvents() {
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const endOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
  return getRangeEvents(startOfDay, endOfDay);
}

function getWeekEvents() {
  const now = new Date();
  const startOfWeek = new Date(now);
  startOfWeek.setDate(now.getDate() - now.getDay()); // Sunday
  startOfWeek.setHours(0, 0, 0, 0);

  const endOfWeek = new Date(startOfWeek);
  endOfWeek.setDate(startOfWeek.getDate() + 6); // Saturday
  endOfWeek.setHours(23, 59, 59, 999);

  return getRangeEvents(startOfWeek, endOfWeek);
}

function getUpcomingEvents(hours) {
  const now = new Date();
  const end = new Date(now.getTime() + hours * 60 * 60 * 1000);
  return getRangeEvents(now, end);
}

function getRangeEvents(startDate, endDate) {
  const calendar = CalendarApp.getDefaultCalendar();
  const events = calendar.getEvents(startDate, endDate);

  return events.map(event => ({
    id: event.getId(),
    title: event.getTitle(),
    start: event.getStartTime().toISOString(),
    end: event.getEndTime().toISOString(),
    location: event.getLocation() || null,
    description: event.getDescription() || null,
    isAllDay: event.isAllDayEvent(),
    guests: event.getGuestList().map(g => g.getEmail()),
    color: event.getColor(),
    status: event.getMyStatus().toString()
  }));
}

function addEvent(title, startTime, endTime, description) {
  const calendar = CalendarApp.getDefaultCalendar();
  const event = calendar.createEvent(title, startTime, endTime, {
    description: description
  });

  return {
    id: event.getId(),
    title: event.getTitle(),
    start: event.getStartTime().toISOString(),
    end: event.getEndTime().toISOString()
  };
}

function jsonResponse(data, status = 200) {
  const output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
