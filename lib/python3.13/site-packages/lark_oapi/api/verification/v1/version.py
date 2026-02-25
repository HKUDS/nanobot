from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.verification: Verification = Verification(config)
