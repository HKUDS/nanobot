from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.task: Task = Task(config)
        self.task_collaborator: TaskCollaborator = TaskCollaborator(config)
        self.task_comment: TaskComment = TaskComment(config)
        self.task_follower: TaskFollower = TaskFollower(config)
        self.task_reminder: TaskReminder = TaskReminder(config)
