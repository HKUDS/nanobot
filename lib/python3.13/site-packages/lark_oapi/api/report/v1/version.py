from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.rule: Rule = Rule(config)
        self.rule_view: RuleView = RuleView(config)
        self.task: Task = Task(config)
