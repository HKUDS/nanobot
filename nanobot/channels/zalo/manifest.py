"""Zalo channel management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "enabled": field("boolean", default=False),
        "token": field("secret"),
        "allowFrom": field("list"),
        "webhookPath": field(default="/webhooks/zalo"),
    },
    required=required_fields("token"),
    official_url="https://bot.zaloplatforms.com/",
)

PLUGIN = ChannelPlugin(
    name="zalo",
    display_name="Zalo",
    runtime=f"{__package__}.runtime:ZaloChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "python-zalo-bot>=0.1.4",
        "fastapi>=0.115.0",
        "uvicorn>=0.34.0",
    ),
)
