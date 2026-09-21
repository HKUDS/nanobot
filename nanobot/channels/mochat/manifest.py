"""MoChat management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "baseUrl": field(default="https://mochat.io"),
        "clawToken": field("secret"),
        "agentUserId": field(),
        "sessions": field("list"),
        "panels": field("list"),
        "allowFrom": field("list"),
        "socketUrl": field(),
        "socketPath": field(default="/socket.io"),
        "socketDisableMsgpack": field("bool", default=False),
        "socketReconnectDelayMs": field("int", default=1000),
        "socketMaxReconnectDelayMs": field("int", default=10000),
        "socketConnectTimeoutMs": field("int", default=10000),
        "refreshIntervalMs": field("int", default=30000),
        "watchTimeoutMs": field("int", default=25000),
        "watchLimit": field("int", default=100),
        "retryDelayMs": field("int", default=500),
        "maxRetryAttempts": field("int", default=0),
        "mention.requireInGroups": field("bool", default=False),
        "groups": field("json", default={}),
        "replyDelayMode": field(default="non-mention"),
        "replyDelayMs": field("int", default=120000),
    },
    required=(required("clawToken"),),
    official_url="https://mochat.io/",
)

PLUGIN = ChannelPlugin(
    name="mochat",
    display_name="MoChat",
    runtime=f"{__package__}.runtime:MochatChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "python-socketio>=5.16.0,<6.0.0",
        "msgpack>=1.1.0,<2.0.0",
    ),
    webui="webui/index.ts",
)
