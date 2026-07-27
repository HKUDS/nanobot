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
