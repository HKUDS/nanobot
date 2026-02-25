from .resource import *


class V2(object):
    def __init__(self, config: Config) -> None:
        self.attachment: Attachment = Attachment(config)
        self.comment: Comment = Comment(config)
        self.custom_field: CustomField = CustomField(config)
        self.custom_field_option: CustomFieldOption = CustomFieldOption(config)
        self.section: Section = Section(config)
        self.task: Task = Task(config)
        self.task_subtask: TaskSubtask = TaskSubtask(config)
        self.tasklist: Tasklist = Tasklist(config)
        self.tasklist_activity_subscription: TasklistActivitySubscription = TasklistActivitySubscription(config)
