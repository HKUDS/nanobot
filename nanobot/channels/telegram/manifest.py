"""Telegram management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.telegram.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "proxy": field("secret"),
        "allowFrom": field("list"),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
    },
    required=(required("token"),),
    official_url="https://t.me/BotFather",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="telegram",
    display_name="Telegram",
    runtime=f"{__package__}.runtime:TelegramChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "python-telegram-bot[socks,webhooks]>=22.6,<23.0",
        "socksio>=1.0.0,<2.0.0",
        "python-socks[asyncio]>=2.8.0,<3.0.0; sys_platform != 'win32'",
    ),
    webui="webui/index.ts",
)
