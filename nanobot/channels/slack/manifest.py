"""Slack management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "appToken": field("secret"),
        "botToken": field("secret"),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
    },
    required=required_fields("appToken", "botToken"),
    official_url="https://api.slack.com/apps",
)

PLUGIN = ChannelPlugin(
    name="slack",
    display_name="Slack",
    runtime=f"{__package__}.runtime:SlackChannel",
    setup=SETUP_SPEC,
    optional_extra="slack",
    webui="webui/index.ts",
)
