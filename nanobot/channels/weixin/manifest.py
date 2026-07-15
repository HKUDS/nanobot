"""WeChat management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "allowFrom": field("list"),
    },
    required=(required("token"),),
    official_url="https://weixin.qq.com/",
)

PLUGIN = ChannelPlugin(
    name="weixin",
    display_name="WeChat",
    runtime=f"{__package__}.runtime:WeixinChannel",
    setup=SETUP_SPEC,
    optional_extra="weixin",
    capabilities=frozenset({"qr_connect"}),
    webui="webui/index.tsx",
)
