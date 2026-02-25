from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.entity: Entity = Entity(config)
        self.message: Message = Message(config)
