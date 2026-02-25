from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.device_apply_record: DeviceApplyRecord = DeviceApplyRecord(config)
        self.device_record: DeviceRecord = DeviceRecord(config)
