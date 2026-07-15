"""Discord management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "allowFrom": field("list", snapshot=False),
        "allowChannels": field("list"),
        "groupPolicy": field("enum", choices=DIRECT_GROUP_POLICIES, default="mention"),
    },
    required=(required("token"),),
    official_url="https://discord.com/developers/applications",
)

PLUGIN = ChannelPlugin(
    name="discord",
    display_name="Discord",
    runtime=f"{__package__}.runtime:DiscordChannel",
    setup=SETUP_SPEC,
    optional_extra="discord",
    webui="webui/index.ts",
)
