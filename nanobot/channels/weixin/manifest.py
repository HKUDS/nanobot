"""WeChat management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelManagementSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.weixin.state import local_state_present
from nanobot.channels.weixin.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "allowFrom": field("list"),
        "baseUrl": field(default="https://ilinkai.weixin.qq.com"),
        "cdnBaseUrl": field(default="https://novac2c.cdn.weixin.qq.com/c2c"),
        "routeTag": field(),
        "stateDir": field(),
        "pollTimeout": field("int", default=35),
        "sendProgress": field("bool", default=False),
        "sendToolHints": field("bool", default=False),
        "replyProgressMessages": field("bool", default=False),
        "replyProgressMaxMessages": field("int", default=2),
        "contextMessageBudget": field("int", default=8),
        "streaming": field("bool", default=True),
        "blockStreaming": field("bool", default=False),
        "blockStreamingMinChars": field("int", default=1200),
        "blockStreamingMaxMessages": field("int", default=3),
    },
    required=(required("token"),),
    official_url="https://weixin.qq.com/",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="weixin",
    display_name="WeChat",
    runtime=f"{__package__}.runtime:WeixinChannel",
    connector=f"{__package__}.connect:WeixinConnectStore",
    setup=SETUP_SPEC,
    management=ChannelManagementSpec(local_state_present=local_state_present),
    dependencies=(
        "qrcode[pil]>=8.0",
        "pycryptodome>=3.20.0",
    ),
    webui="webui/index.tsx",
)
