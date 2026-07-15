"""Signal management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "phoneNumber": field(),
        "daemonHost": field(),
        "daemonPort": field("int"),
        "allowFrom": field("list", snapshot=False),
        "dm.allowFrom": field("list"),
        "group.allowFrom": field("list"),
    },
    required=(required("phoneNumber"),),
    official_url="https://github.com/bbernhard/signal-cli-rest-api",
)

PLUGIN = ChannelPlugin(
    name="signal",
    display_name="Signal",
    runtime=f"{__package__}.runtime:SignalChannel",
    setup=SETUP_SPEC,
    webui="webui/index.ts",
)
