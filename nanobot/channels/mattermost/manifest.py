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
        "groupPolicyInThread": field("enum", choices=GROUP_POLICIES, default="mention"),
        "allowFrom": field("list"),
        "allowFromMatchMode": field(
            "enum", choices={"id", "username", "email"}, default="id"
        ),
        "groupAllowFrom": field("list"),
        "replyInThread": field("bool", default=True),
        "includeThreadContext": field("bool", default=True),
        "threadContextLimit": field("int", default=20),
        "streaming": field("bool", default=True),
        "reactEmoji": field(default="eyes"),
        "doneEmoji": field(default="white_check_mark"),
        "sendProgress": field("bool", default=True),
        "sendToolHints": field("bool", default=True),
        "dm.enabled": field("bool", default=True),
        "dm.policy": field("enum", choices={"open", "allowlist"}, default="open"),
        "dm.allowFrom": field("list"),
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
