from .resource import *


class V3(object):
    def __init__(self, config: Config) -> None:
        self.app_access_token: AppAccessToken = AppAccessToken(config)
        self.app_ticket: AppTicket = AppTicket(config)
        self.tenant_access_token: TenantAccessToken = TenantAccessToken(config)
