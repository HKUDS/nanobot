"""Matrix management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, one_of, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.matrix.validation import validate
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "homeserver": field(default="https://matrix.org"),
        "userId": field(),
        "password": field("secret"),
        "accessToken": field("secret"),
        "deviceId": field(),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="open"),
        "allowFrom": field("list"),
        "e2eeEnabled": field("bool", default=False),
        "sasVerification": field("bool", default=False),
        "syncStopGraceSeconds": field("int", default=2),
        "maxMediaBytes": field("int", default=20 * 1024 * 1024),
        "maxConcurrentMediaDownloads": field("int", default=2),
        "groupAllowFrom": field("list"),
        "allowRoomMentions": field("bool", default=False),
        "streaming": field("bool", default=False),
        "proxy": field(),
    },
    required=(
        *required_fields("homeserver", "userId"),
        one_of(("password",), ("accessToken", "deviceId")),
    ),
    official_url="https://matrix.org/ecosystem/clients/",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="matrix",
    display_name="Matrix",
    runtime=f"{__package__}.runtime:MatrixChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "matrix-nio[e2e]>=0.25.2; sys_platform != 'win32'",
        "matrix-nio>=0.25.2; sys_platform == 'win32'",
        "aiohttp>=3.9.0,<4.0.0",
        "mistune>=3.0.0,<4.0.0",
        "nh3>=0.2.17,<1.0.0",
    ),
    webui="webui/index.ts",
)
