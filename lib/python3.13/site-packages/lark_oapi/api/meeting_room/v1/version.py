from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.meeting_room: MeetingRoom = MeetingRoom(config)
