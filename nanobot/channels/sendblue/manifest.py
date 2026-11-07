"""Dependency-free Sendblue setup contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

PLUGIN = ChannelPlugin(
    name="sendblue",
    display_name="Sendblue (iMessage / SMS)",
    runtime=f"{__package__}.runtime:SendblueChannel",
    setup=ChannelSetupSpec(
        official_url="https://docs.sendblue.com/getting-started/credentials",
        fields={
            "apiKey": field("secret"),
            "apiSecret": field("secret"),
            "fromNumber": field(),
            "webhookSecret": field("secret"),
            "host": field(default="127.0.0.1"),
            "port": field("int", default=3980),
            "allowFrom": field("list"),
        },
        required=required_fields("apiKey", "apiSecret", "fromNumber", "webhookSecret", "allowFrom"),
    ),
)
