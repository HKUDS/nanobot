"""Telegram management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "allowFrom": field("list"),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
    },
    required=(required("token"),),
    official_url="https://t.me/BotFather",
)

PLUGIN = ChannelPlugin(
    name="telegram",
    display_name="Telegram",
    runtime=f"{__package__}.runtime:TelegramChannel",
    setup=SETUP_SPEC,
    optional_extra="telegram",
    webui="webui/index.ts",
)
