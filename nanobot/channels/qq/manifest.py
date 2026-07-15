"""QQ management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "appId": field(),
        "secret": field("secret"),
        "allowFrom": field("list"),
        "msgFormat": field("enum", choices={"plain", "markdown"}, default="plain"),
    },
    required=required_fields("appId", "secret"),
    official_url="https://q.qq.com/",
)

PLUGIN = ChannelPlugin(
    name="qq",
    display_name="QQ",
    runtime=f"{__package__}.runtime:QQChannel",
    setup=SETUP_SPEC,
    optional_extra="qq",
    webui="webui/index.ts",
)
