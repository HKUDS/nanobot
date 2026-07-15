"""WhatsApp management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "allowFrom": field("list", snapshot=False),
        "groupPolicy": field(
            "enum",
            choices=DIRECT_GROUP_POLICIES,
            default="open",
            snapshot=False,
        ),
        "databasePath": field(writable=False, snapshot=False),
    },
    official_url="https://faq.whatsapp.com/",
)

PLUGIN = ChannelPlugin(
    name="whatsapp",
    display_name="WhatsApp",
    runtime=f"{__package__}.runtime:WhatsAppChannel",
    setup=SETUP_SPEC,
    optional_extra="whatsapp",
    capabilities=frozenset({"qr_connect"}),
    webui="webui/index.ts",
)
