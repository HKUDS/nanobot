from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.collaboration_rule: CollaborationRule = CollaborationRule(config)
        self.collaboration_tenant: CollaborationTenant = CollaborationTenant(config)
        self.collboration_share_entity: CollborationShareEntity = CollborationShareEntity(config)
        self.department: Department = Department(config)
        self.employee: Employee = Employee(config)
