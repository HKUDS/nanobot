from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.activity: Activity = Activity(config)
        self.additional_information: AdditionalInformation = AdditionalInformation(config)
        self.additional_informations_batch: AdditionalInformationsBatch = AdditionalInformationsBatch(config)
        self.indicator: Indicator = Indicator(config)
        self.metric_detail: MetricDetail = MetricDetail(config)
        self.metric_field: MetricField = MetricField(config)
        self.metric_lib: MetricLib = MetricLib(config)
        self.metric_tag: MetricTag = MetricTag(config)
        self.metric_template: MetricTemplate = MetricTemplate(config)
        self.question: Question = Question(config)
        self.review_data: ReviewData = ReviewData(config)
        self.review_template: ReviewTemplate = ReviewTemplate(config)
        self.reviewee: Reviewee = Reviewee(config)
        self.stage_task: StageTask = StageTask(config)
        self.user_group_user_rel: UserGroupUserRel = UserGroupUserRel(config)
        self.user_info: UserInfo = UserInfo(config)
