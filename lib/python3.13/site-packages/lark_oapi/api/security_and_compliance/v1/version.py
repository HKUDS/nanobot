from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.openapi_log: OpenapiLog = OpenapiLog(config)
