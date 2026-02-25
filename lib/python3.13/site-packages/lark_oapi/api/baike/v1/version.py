from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.classification: Classification = Classification(config)
        self.draft: Draft = Draft(config)
        self.entity: Entity = Entity(config)
        self.file: File = File(config)
