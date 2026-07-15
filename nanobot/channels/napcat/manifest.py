"""NapCat management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "wsUrl": field(),
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
    optional_extra="napcat",
    webui="webui/index.ts",
)
