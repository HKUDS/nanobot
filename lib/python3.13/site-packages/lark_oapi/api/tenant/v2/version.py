from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.tenant: Tenant = Tenant(config)
        self.tenant_product_assign_info: TenantProductAssignInfo = TenantProductAssignInfo(config)
