"""NapCat management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "wsUrl": field(default="ws://127.0.0.1:3001"),
        "accessToken": field("secret"),
        "allowFrom": field("list"),
        "groupPolicy": field("enum", choices=DIRECT_GROUP_POLICIES, default="mention"),
    },
    required=(required("wsUrl"),),
    official_url="https://napneko.github.io/",
)

PLUGIN = ChannelPlugin(
    name="napcat",
    display_name="NapCat",
    runtime=f"{__package__}.runtime:NapcatChannel",
    setup=SETUP_SPEC,
    dependencies=("aiohttp>=3.9.0,<4.0.0",),
    webui="webui/index.ts",
)
