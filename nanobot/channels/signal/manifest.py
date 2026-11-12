"""Signal management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "phoneNumber": field(),
        "daemonHost": field(default="localhost"),
        "daemonPort": field("int", default=8080),
        "dm.allowFrom": field("list"),
        "group.allowFrom": field("list"),
        "groupMessageBufferSize": field("int", default=20),
        "attachmentsDir": field(),
        "dm.enabled": field("bool", default=True),
        "dm.policy": field("enum", choices={"open", "allowlist"}, default="allowlist"),
        "group.enabled": field("bool", default=False),
        "group.policy": field("enum", choices={"open", "allowlist"}, default="allowlist"),
        "group.requireMention": field("bool", default=True),
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
