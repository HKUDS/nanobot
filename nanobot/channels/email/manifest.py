"""Email management contract."""

from nanobot.channels._manifest import field, one_of, required_fields
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
        # Microsoft OAuth (delegated user auth) for Office365/Outlook. Alternative to
        # imapPassword/smtpPassword; run `nanobot channels login email` after setting these.
        "oauthTenantId": field(),
        "oauthClientId": field(),
        "oauthClientSecret": field("secret"),
    },
    required=(
        *required_fields(
            "consentGranted",
            "imapHost",
            "imapUsername",
            "smtpHost",
            "smtpUsername",
        ),
        one_of(
            ("imapPassword", "smtpPassword"),
            ("oauthTenantId", "oauthClientId", "oauthClientSecret"),
        ),
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
