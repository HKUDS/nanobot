from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.admin_dept_stat: AdminDeptStat = AdminDeptStat(config)
        self.admin_user_stat: AdminUserStat = AdminUserStat(config)
        self.audit_info: AuditInfo = AuditInfo(config)
        self.badge: Badge = Badge(config)
        self.badge_grant: BadgeGrant = BadgeGrant(config)
        self.badge_image: BadgeImage = BadgeImage(config)
        self.password: Password = Password(config)
