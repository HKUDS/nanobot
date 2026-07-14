"""WeChat management contract."""

from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.manifests._shared import field, required
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
    runtime="nanobot.channels.weixin.runtime:WeixinChannel",
    setup=SETUP_SPEC,
    optional_extra="weixin",
    capabilities=frozenset({"qr_connect"}),
    webui="webui/index.tsx",
)
