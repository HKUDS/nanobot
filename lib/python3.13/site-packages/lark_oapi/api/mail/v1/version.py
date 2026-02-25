from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.mailgroup: Mailgroup = Mailgroup(config)
        self.mailgroup_alias: MailgroupAlias = MailgroupAlias(config)
        self.mailgroup_manager: MailgroupManager = MailgroupManager(config)
        self.mailgroup_member: MailgroupMember = MailgroupMember(config)
        self.mailgroup_permission_member: MailgroupPermissionMember = MailgroupPermissionMember(config)
        self.public_mailbox: PublicMailbox = PublicMailbox(config)
        self.public_mailbox_alias: PublicMailboxAlias = PublicMailboxAlias(config)
        self.public_mailbox_member: PublicMailboxMember = PublicMailboxMember(config)
        self.user: User = User(config)
        self.user_mailbox: UserMailbox = UserMailbox(config)
        self.user_mailbox_alias: UserMailboxAlias = UserMailboxAlias(config)
        self.user_mailbox_event: UserMailboxEvent = UserMailboxEvent(config)
        self.user_mailbox_folder: UserMailboxFolder = UserMailboxFolder(config)
        self.user_mailbox_mail_contact: UserMailboxMailContact = UserMailboxMailContact(config)
        self.user_mailbox_message: UserMailboxMessage = UserMailboxMessage(config)
        self.user_mailbox_message_attachment: UserMailboxMessageAttachment = UserMailboxMessageAttachment(config)
        self.user_mailbox_rule: UserMailboxRule = UserMailboxRule(config)
