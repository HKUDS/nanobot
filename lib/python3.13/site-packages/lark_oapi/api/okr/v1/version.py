from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.image: Image = Image(config)
        self.okr: Okr = Okr(config)
        self.period: Period = Period(config)
        self.period_rule: PeriodRule = PeriodRule(config)
        self.progress_record: ProgressRecord = ProgressRecord(config)
        self.review: Review = Review(config)
        self.user_okr: UserOkr = UserOkr(config)
