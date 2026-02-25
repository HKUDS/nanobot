from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.batch_message: BatchMessage = BatchMessage(config)
        self.chat: Chat = Chat(config)
        self.chat_access_event: ChatAccessEvent = ChatAccessEvent(config)
        self.chat_announcement: ChatAnnouncement = ChatAnnouncement(config)
        self.chat_managers: ChatManagers = ChatManagers(config)
        self.chat_member_bot: ChatMemberBot = ChatMemberBot(config)
        self.chat_member_user: ChatMemberUser = ChatMemberUser(config)
        self.chat_members: ChatMembers = ChatMembers(config)
        self.chat_menu_item: ChatMenuItem = ChatMenuItem(config)
        self.chat_menu_tree: ChatMenuTree = ChatMenuTree(config)
        self.chat_moderation: ChatModeration = ChatModeration(config)
        self.chat_tab: ChatTab = ChatTab(config)
        self.chat_top_notice: ChatTopNotice = ChatTopNotice(config)
        self.file: File = File(config)
        self.image: Image = Image(config)
        self.message: Message = Message(config)
        self.message_reaction: MessageReaction = MessageReaction(config)
        self.message_resource: MessageResource = MessageResource(config)
        self.pin: Pin = Pin(config)
        self.thread: Thread = Thread(config)
