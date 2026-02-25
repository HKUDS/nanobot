from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.custom_workplace_access_data: CustomWorkplaceAccessData = CustomWorkplaceAccessData(config)
        self.workplace_access_data: WorkplaceAccessData = WorkplaceAccessData(config)
        self.workplace_block_access_data: WorkplaceBlockAccessData = WorkplaceBlockAccessData(config)
