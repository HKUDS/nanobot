"""WebSocket management contract."""

from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={},
    official_url="http://127.0.0.1:8765",
)

PLUGIN = ChannelPlugin(
    name="websocket",
    display_name="WebSocket",
    runtime=f"{__package__}.runtime:WebSocketChannel",
    setup=SETUP_SPEC,
    default_enabled=True,
    capabilities=frozenset({"always_enabled"}),
    webui="webui/index.ts",
)
