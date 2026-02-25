from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.approval_info: ApprovalInfo = ApprovalInfo(config)
        self.archive_rule: ArchiveRule = ArchiveRule(config)
        self.file: File = File(config)
        self.group: Group = Group(config)
        self.leave_accrual_record: LeaveAccrualRecord = LeaveAccrualRecord(config)
        self.leave_employ_expire_record: LeaveEmployExpireRecord = LeaveEmployExpireRecord(config)
        self.shift: Shift = Shift(config)
        self.user_approval: UserApproval = UserApproval(config)
        self.user_daily_shift: UserDailyShift = UserDailyShift(config)
        self.user_flow: UserFlow = UserFlow(config)
        self.user_setting: UserSetting = UserSetting(config)
        self.user_stats_data: UserStatsData = UserStatsData(config)
        self.user_stats_field: UserStatsField = UserStatsField(config)
        self.user_stats_view: UserStatsView = UserStatsView(config)
        self.user_task: UserTask = UserTask(config)
        self.user_task_remedy: UserTaskRemedy = UserTaskRemedy(config)
