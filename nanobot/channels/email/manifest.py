"""Email management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "consentGranted": field("bool", default=False),
        "imapHost": field(),
        "imapPort": field("int"),
        "imapUsername": field(),
        "imapPassword": field("secret"),
        "smtpHost": field(),
        "smtpPort": field("int"),
        "smtpUsername": field(),
        "smtpPassword": field("secret"),
        "fromAddress": field(),
        "pollIntervalSeconds": field("int"),
        "allowFrom": field("list"),
        "verifyDkim": field("bool", default=True),
        "verifySpf": field("bool", default=True),
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
)

PLUGIN = ChannelPlugin(
    name="email",
    display_name="Email",
    runtime=f"{__package__}.runtime:EmailChannel",
    setup=SETUP_SPEC,
    webui="webui/index.ts",
)
