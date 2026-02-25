from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.access_record: AccessRecord = AccessRecord(config)
        self.access_record_access_photo: AccessRecordAccessPhoto = AccessRecordAccessPhoto(config)
        self.device: Device = Device(config)
        self.rule_external: RuleExternal = RuleExternal(config)
        self.user: User = User(config)
        self.user_face: UserFace = UserFace(config)
        self.visitor: Visitor = Visitor(config)
