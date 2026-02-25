from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.attachment: Attachment = Attachment(config)
        self.employee: Employee = Employee(config)
