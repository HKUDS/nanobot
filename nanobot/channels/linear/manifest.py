"""Dependency-free management contract for the native Linear Agent channel."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelManagementSpec, ChannelSetupSpec
from nanobot.channels.linear.state import local_state_present
from nanobot.channels.linear.validation import validate
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "clientId": field(),
        "clientSecret": field("secret"),
        "webhookSigningSecret": field("secret"),
        "publicBaseUrl": field(),
        "host": field(default="0.0.0.0"),
        "port": field("int", default=3979),
        "webhookPath": field(default="/linear/webhook"),
        "oauthCallbackPath": field(default="/linear/oauth/callback"),
        "allowFrom": field("list"),
    },
    required=required_fields(
        "clientId",
        "clientSecret",
        "webhookSigningSecret",
        "publicBaseUrl",
    ),
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="linear",
    display_name="Linear",
    runtime=f"{__package__}.runtime:LinearChannel",
    connector=f"{__package__}.connect:LinearConnectStore",
    setup=SETUP_SPEC,
    management=ChannelManagementSpec(local_state_present=local_state_present),
    webui="webui/index.tsx",
)
