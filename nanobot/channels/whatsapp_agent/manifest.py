"""WhatsApp Agent Platform management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.whatsapp_agent.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "token": field("secret"),
        "allowFrom": field("list"),
        "stateDir": field(),
        "pollTimeout": field("int", default=25),
        "markRead": field("bool", default=True),
        "typingIndicator": field("bool", default=True),
        "downloadMedia": field("bool", default=True),
        "deleteMediaAfterDownload": field("bool", default=False),
        "maxMediaMb": field("int", default=16),
        "retryAmbiguousSends": field("bool", default=False),
        "sendProgress": field("bool", default=False),
        "sendToolHints": field("bool", default=False),
    },
    required=(required("token"),),
    official_url="https://faq.whatsapp.com/1050934623978152",
    validator=validate,
    verifies_connection=True,
)

PLUGIN = ChannelPlugin(
    name="whatsapp_agent",
    display_name="WhatsApp Agent Platform",
    runtime=f"{__package__}.runtime:WhatsAppAgentChannel",
    setup=SETUP_SPEC,
    dependencies=(),
    webui="webui/index.ts",
)
