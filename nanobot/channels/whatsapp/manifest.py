"""WhatsApp management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field
from nanobot.channels.contracts import ChannelManagementSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.whatsapp.state import local_state_present
from nanobot.channels.whatsapp.validation import validate

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
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="whatsapp",
    display_name="WhatsApp",
    runtime=f"{__package__}.runtime:WhatsAppChannel",
    setup=SETUP_SPEC,
    management=ChannelManagementSpec(local_state_present=local_state_present),
    dependencies=(
        "neonize>=0.3.18.post0,<0.4.0",
        "segno>=1.6.1,<2.0.0",
    ),
    webui="webui/index.ts",
)
