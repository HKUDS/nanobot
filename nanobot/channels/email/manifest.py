"""Email management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.email.validation import validate
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "consentGranted": field("bool", default=False),
        "imapHost": field(),
        "imapPort": field("int", default=993),
        "imapUsername": field(),
        "imapPassword": field("secret"),
        "smtpHost": field(),
        "smtpPort": field("int", default=587),
        "smtpUsername": field(),
        "smtpPassword": field("secret"),
        "fromAddress": field(),
        "pollIntervalSeconds": field("int", default=30),
        "allowFrom": field("list"),
        "verifyDkim": field("bool", default=True),
        "verifySpf": field("bool", default=True),
        "imapMailbox": field(default="INBOX"),
        "imapUseSsl": field("bool", default=True),
        "smtpUseTls": field("bool", default=True),
        "smtpUseSsl": field("bool", default=False),
        "autoReplyEnabled": field("bool", default=True),
        "markSeen": field("bool", default=True),
        "postAction": field("enum", choices={"delete", "move"}),
        "postActionMoveMailbox": field(),
        "postActionExpunge": field("bool", default=False),
        "postActionIgnoreSkipped": field("bool", default=True),
        "maxBodyChars": field("int", default=12000),
        "subjectPrefix": field(default="Re: "),
        "allowedAttachmentTypes": field("list"),
        "maxAttachmentSize": field("int", default=2_000_000),
        "maxAttachmentsPerEmail": field("int", default=5),
    },
    required=required_fields(
        "consentGranted",
        "imapHost",
        "imapUsername",
        "imapPassword",
        "smtpHost",
        "smtpUsername",
        "smtpPassword",
    ),
    official_url="https://support.google.com/accounts/answer/185833",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="email",
    display_name="Email",
    runtime=f"{__package__}.runtime:EmailChannel",
    setup=SETUP_SPEC,
    webui="webui/index.ts",
)
