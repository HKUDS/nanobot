from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.space: Space = Space(config)
        self.space_member: SpaceMember = SpaceMember(config)
        self.space_node: SpaceNode = SpaceNode(config)
        self.space_setting: SpaceSetting = SpaceSetting(config)
        self.task: Task = Task(config)
