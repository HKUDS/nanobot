from .resource import *


class V4(object):
    def __init__(self, config: Config) -> None:
        self.calendar: Calendar = Calendar(config)
        self.calendar_acl: CalendarAcl = CalendarAcl(config)
        self.calendar_event: CalendarEvent = CalendarEvent(config)
        self.calendar_event_attendee: CalendarEventAttendee = CalendarEventAttendee(config)
        self.calendar_event_attendee_chat_member: CalendarEventAttendeeChatMember = CalendarEventAttendeeChatMember(
            config)
        self.calendar_event_meeting_chat: CalendarEventMeetingChat = CalendarEventMeetingChat(config)
        self.calendar_event_meeting_minute: CalendarEventMeetingMinute = CalendarEventMeetingMinute(config)
        self.exchange_binding: ExchangeBinding = ExchangeBinding(config)
        self.freebusy: Freebusy = Freebusy(config)
        self.setting: Setting = Setting(config)
        self.timeoff_event: TimeoffEvent = TimeoffEvent(config)
