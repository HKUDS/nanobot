from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.agent: Agent = Agent(config)
        self.agent_schedules: AgentSchedules = AgentSchedules(config)
        self.agent_schedule: AgentSchedule = AgentSchedule(config)
        self.agent_skill: AgentSkill = AgentSkill(config)
        self.agent_skill_rule: AgentSkillRule = AgentSkillRule(config)
        self.bot_message: BotMessage = BotMessage(config)
        self.category: Category = Category(config)
        self.event: Event = Event(config)
        self.faq: Faq = Faq(config)
        self.notification: Notification = Notification(config)
        self.ticket: Ticket = Ticket(config)
        self.ticket_message: TicketMessage = TicketMessage(config)
        self.ticket_customized_field: TicketCustomizedField = TicketCustomizedField(config)
