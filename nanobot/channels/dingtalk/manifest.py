"""DingTalk management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "clientId": field(),
        "clientSecret": field("secret"),
        "allowFrom": field("list"),
    },
    required=required_fields("clientId", "clientSecret"),
    official_url="https://open.dingtalk.com/",
)

PLUGIN = ChannelPlugin(
    name="dingtalk",
    display_name="DingTalk",
    runtime=f"{__package__}.runtime:DingTalkChannel",
    setup=SETUP_SPEC,
    optional_extra="dingtalk",
    webui="webui/index.ts",
)
