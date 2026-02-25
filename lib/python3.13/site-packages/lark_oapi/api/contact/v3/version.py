from .resource import *


class V3(object):
    def __init__(self, config: Config) -> None:
        self.custom_attr: CustomAttr = CustomAttr(config)
        self.custom_attr_event: CustomAttrEvent = CustomAttrEvent(config)
        self.department: Department = Department(config)
        self.employee_type_enum: EmployeeTypeEnum = EmployeeTypeEnum(config)
        self.functional_role: FunctionalRole = FunctionalRole(config)
        self.functional_role_member: FunctionalRoleMember = FunctionalRoleMember(config)
        self.group: Group = Group(config)
        self.group_member: GroupMember = GroupMember(config)
        self.job_family: JobFamily = JobFamily(config)
        self.job_level: JobLevel = JobLevel(config)
        self.job_title: JobTitle = JobTitle(config)
        self.scope: Scope = Scope(config)
        self.unit: Unit = Unit(config)
        self.user: User = User(config)
        self.work_city: WorkCity = WorkCity(config)
