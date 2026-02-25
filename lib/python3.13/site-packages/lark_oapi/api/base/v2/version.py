from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.app_role: AppRole = AppRole(config)
