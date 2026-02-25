from .resource import *


class V6(object):
    def __init__(self, config: Config) -> None:
        self.app_badge: AppBadge = AppBadge(config)
        self.app_recommend_rule: AppRecommendRule = AppRecommendRule(config)
        self.application: Application = Application(config)
        self.application_app_usage: ApplicationAppUsage = ApplicationAppUsage(config)
        self.application_app_version: ApplicationAppVersion = ApplicationAppVersion(config)
        self.application_collaborators: ApplicationCollaborators = ApplicationCollaborators(config)
        self.application_contacts_range: ApplicationContactsRange = ApplicationContactsRange(config)
        self.application_feedback: ApplicationFeedback = ApplicationFeedback(config)
        self.application_management: ApplicationManagement = ApplicationManagement(config)
        self.application_owner: ApplicationOwner = ApplicationOwner(config)
        self.application_visibility: ApplicationVisibility = ApplicationVisibility(config)
        self.bot: Bot = Bot(config)
        self.scope: Scope = Scope(config)
