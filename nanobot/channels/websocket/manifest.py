from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.websocket.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={},
    official_url="http://127.0.0.1:8765",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="websocket",
    reply_format=(
        r"For math meant to render, use LaTeX with `\(...\)` for inline math and `\[...\]` for display math. "
        "Keep those formulas outside inline code and fenced code blocks."
    ),
    display_name="WebSocket",
    runtime=f"{__package__}.runtime:WebSocketChannel",
    setup=SETUP_SPEC,
    default_enabled=True,
    capabilities=frozenset({"always_enabled"}),
    webui="webui/index.ts",
)
