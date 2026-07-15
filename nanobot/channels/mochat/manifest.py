"""MoChat management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "baseUrl": field(default="https://mochat.io"),
        "clawToken": field("secret"),
        "agentUserId": field(),
        "sessions": field("list"),
        "panels": field("list"),
        "allowFrom": field("list"),
    },
    required=(required("clawToken"),),
    official_url="https://mochat.io/",
)

PLUGIN = ChannelPlugin(
    name="mochat",
    display_name="MoChat",
    runtime=f"{__package__}.runtime:MochatChannel",
    setup=SETUP_SPEC,
    optional_extra="mochat",
    settings_visible=False,
)
