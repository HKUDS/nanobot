"""Microsoft Teams management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "appId": field(),
        "appPassword": field("secret"),
        "tenantId": field(),
        "path": field(default="/api/messages"),
        "allowFrom": field("list"),
    },
    required=required_fields("appId", "appPassword"),
    official_url="https://dev.teams.microsoft.com/apps",
)

PLUGIN = ChannelPlugin(
    name="msteams",
    display_name="Microsoft Teams",
    runtime=f"{__package__}.runtime:MSTeamsChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "PyJWT>=2.0,<3.0",
        "cryptography>=41.0",
    ),
    webui="webui/index.ts",
)
