"""Mattermost management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "serverUrl": field(),
        "token": field("secret"),
        "teamId": field(),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
        "allowFrom": field("list"),
    },
    required=required_fields("serverUrl", "token"),
    official_url="https://developers.mattermost.com/integrate/reference/bot-accounts/",
)

PLUGIN = ChannelPlugin(
    name="mattermost",
    display_name="Mattermost",
    runtime=f"{__package__}.runtime:MattermostChannel",
    setup=SETUP_SPEC,
    webui="webui/index.ts",
)
