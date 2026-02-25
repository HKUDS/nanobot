from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.archive: Archive = Archive(config)
        self.change_reason: ChangeReason = ChangeReason(config)
        self.indicator: Indicator = Indicator(config)
        self.item: Item = Item(config)
        self.item_category: ItemCategory = ItemCategory(config)
        self.lump_sum_payment: LumpSumPayment = LumpSumPayment(config)
        self.plan: Plan = Plan(config)
        self.recurring_payment: RecurringPayment = RecurringPayment(config)
        self.social_archive: SocialArchive = SocialArchive(config)
        self.social_archive_adjust_record: SocialArchiveAdjustRecord = SocialArchiveAdjustRecord(config)
        self.social_insurance: SocialInsurance = SocialInsurance(config)
        self.social_plan: SocialPlan = SocialPlan(config)
