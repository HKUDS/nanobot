from .resource import *


class V4(object):
    def __init__(self, config: Config) -> None:
        self.approval: Approval = Approval(config)
        self.external_approval: ExternalApproval = ExternalApproval(config)
        self.external_instance: ExternalInstance = ExternalInstance(config)
        self.external_task: ExternalTask = ExternalTask(config)
        self.instance: Instance = Instance(config)
        self.instance_comment: InstanceComment = InstanceComment(config)
        self.task: Task = Task(config)
