"""Slack management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.slack.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "appToken": field("secret"),
        "botToken": field("secret"),
        "groupPolicy": field("enum", choices=GROUP_POLICIES, default="mention"),
        "mode": field("enum", choices={"socket"}, default="socket"),
        "webhookPath": field(default="/slack/events"),
        "replyInThread": field("bool", default=True),
        "reactEmoji": field(default="eyes"),
        "doneEmoji": field(default="white_check_mark"),
        "includeThreadContext": field("bool", default=True),
        "threadContextLimit": field("int", default=20),
        "allowFrom": field("list"),
        "groupAllowFrom": field("list"),
        "groupRequireMention": field("bool", default=False),
        "dm.enabled": field("bool", default=True),
        "dm.policy": field("enum", choices={"open", "allowlist"}, default="open"),
        "dm.allowFrom": field("list"),
        "proxy": field(),
    },
    required=required_fields("appToken", "botToken"),
    official_url="https://api.slack.com/apps",
    validator=validate,
    verifies_connection=True,
)

PLUGIN = ChannelPlugin(
    name="slack",
    display_name="Slack",
    runtime=f"{__package__}.runtime:SlackChannel",
    setup=SETUP_SPEC,
    dependencies=(
        "aiohttp>=3.9.0,<4.0.0",
        "slack-sdk>=3.39.0,<4.0.0",
        "slackify-markdown>=0.2.0,<1.0.0",
    ),
    webui="webui/index.ts",
)
