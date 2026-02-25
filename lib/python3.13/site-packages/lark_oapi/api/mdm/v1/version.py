from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.user_auth_data_relation: UserAuthDataRelation = UserAuthDataRelation(config)
