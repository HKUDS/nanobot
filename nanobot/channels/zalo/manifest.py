"""Zalo channel management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "mode": field("enum", choices={"webhook", "polling"}, default="webhook"),
        "botToken": field("secret"),
        "webhookSecret": field("secret"),
        "webhookPath": field(default="/webhooks/zalo"),
        "webhookHost": field(default="0.0.0.0"),
        "webhookPort": field("int", default=8443),
        "allowFrom": field("list"),
    },
    required=required_fields("botToken"),
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
