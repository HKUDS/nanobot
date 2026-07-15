"""Dependency-free Feishu/Lark management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "appId": field(snapshot=False),
        "appSecret": field("secret", snapshot=False),
        "domain": field(
            "enum",
            choices={"feishu", "lark"},
            default="feishu",
            snapshot=False,
        ),
        "groupPolicy": field(
            "enum",
            choices=DIRECT_GROUP_POLICIES,
            default="mention",
            snapshot=False,
        ),
        "allowFrom": field("list", snapshot=False),
        "topicIsolation": field("bool", snapshot=False),
    },
    required=required_fields("appId", "appSecret"),
    official_url="https://open.feishu.cn/app",
    multi_instance=True,
)

PLUGIN = ChannelPlugin(
    name="feishu",
    display_name="Feishu",
    runtime=f"{__package__}.runtime:FeishuChannel",
    setup=SETUP_SPEC,
    optional_extra="feishu",
    capabilities=frozenset({"multi_instance", "qr_connect"}),
    webui="webui/index.tsx",
)
