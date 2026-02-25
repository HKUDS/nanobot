from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.alert: Alert = Alert(config)
        self.export: Export = Export(config)
        self.meeting: Meeting = Meeting(config)
        self.meeting_recording: MeetingRecording = MeetingRecording(config)
        self.meeting_list: MeetingList = MeetingList(config)
        self.participant_list: ParticipantList = ParticipantList(config)
        self.participant_quality_list: ParticipantQualityList = ParticipantQualityList(config)
        self.report: Report = Report(config)
        self.reserve: Reserve = Reserve(config)
        self.reserve_config: ReserveConfig = ReserveConfig(config)
        self.reserve_config_admin: ReserveConfigAdmin = ReserveConfigAdmin(config)
        self.reserve_config_disable_inform: ReserveConfigDisableInform = ReserveConfigDisableInform(config)
        self.reserve_config_form: ReserveConfigForm = ReserveConfigForm(config)
        self.resource_reservation_list: ResourceReservationList = ResourceReservationList(config)
        self.room: Room = Room(config)
        self.room_config: RoomConfig = RoomConfig(config)
        self.room_level: RoomLevel = RoomLevel(config)
        self.scope_config: ScopeConfig = ScopeConfig(config)
