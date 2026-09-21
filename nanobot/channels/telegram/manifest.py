"""Telegram management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.telegram.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "proxy": field(),
        "allowFrom": field("list"),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
        "mode": field("enum", choices={"polling", "webhook"}, default="polling"),
        "replyToMessage": field("bool", default=False),
        "reactEmoji": field(default="👀"),
        "connectionPoolSize": field("int", default=32),
        "poolTimeout": field("float", default=5.0),
        "streaming": field("bool", default=True),
        "inlineKeyboards": field("bool", default=False),
        "richMessages": field("bool", default=False),
        "streamEditInterval": field("float", default=0.6),
        "webhookUrl": field(),
        "webhookListenHost": field(default="127.0.0.1"),
        "webhookListenPort": field("int", default=8081),
        "webhookPath": field(default="/telegram"),
        "webhookSecretToken": field("secret"),
        "webhookMaxConnections": field("int", default=4),
    },
    required=(required("token"),),
    official_url="https://t.me/BotFather",
    validator=validate,
    verifies_connection=True,
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
