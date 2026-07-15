"""Matrix management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, one_of, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "homeserver": field(),
        "userId": field(),
        "password": field("secret"),
        "accessToken": field("secret"),
        "deviceId": field(),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="open"),
        "allowFrom": field("list", writable=False),
    },
    required=(
        *required_fields("homeserver", "userId"),
        one_of(("password",), ("accessToken", "deviceId")),
    ),
    official_url="https://matrix.org/ecosystem/clients/",
)

PLUGIN = ChannelPlugin(
    name="matrix",
    display_name="Matrix",
    runtime=f"{__package__}.runtime:MatrixChannel",
    setup=SETUP_SPEC,
    optional_extra="matrix",
    webui="webui/index.ts",
)
