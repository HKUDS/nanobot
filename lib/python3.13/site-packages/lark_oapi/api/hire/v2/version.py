from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.interview_record: InterviewRecord = InterviewRecord(config)
        self.talent: Talent = Talent(config)
