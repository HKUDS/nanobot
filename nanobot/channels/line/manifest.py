"""LINE management contract.

LINE Messaging API webhook channel.
Requires a LINE Bot channel (channel-access-token + channel-secret).
"""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "channelAccessToken": field("secret"),
        "channelSecret": field("secret"),
        "allowFrom": field("list"),
        "groupPolicy": field("enum", choices=("mention", "all"), default="mention"),
    },
    required=(required("channelAccessToken"), required("channelSecret")),
    official_url="https://developers.line.biz/console/",
)

PLUGIN = ChannelPlugin(
    name="line",
    display_name="LINE",
    runtime=f"{__package__}.runtime:LineChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "line-bot-sdk>=3.0.0,<4.0.0",
    ),
    webui="webui/index.ts",
)
