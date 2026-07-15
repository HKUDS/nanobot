"""Shared channel setup contract for configuration, display, and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldKind = Literal["string", "secret", "list", "bool", "int", "enum"]
RouteFieldType = str | tuple[str, set[str]]


@dataclass(frozen=True)
class ChannelFieldSpec:
    """One channel field exposed through the settings contract."""

    kind: FieldKind = "string"
    choices: frozenset[str] = frozenset()
    writable: bool = True
    snapshot: bool = True

    @property
    def route_type(self) -> RouteFieldType:
        if self.kind == "enum":
            return ("enum", set(self.choices))
        return self.kind


@dataclass(frozen=True)
class SetupRequirement:
    """A requirement satisfied by any one complete field group."""

    alternatives: tuple[tuple[str, ...], ...]

    def is_satisfied(self, values: Any) -> bool:
        return any(
            all(channel_value_present(channel_field_value(values, field)) for field in group)
            for group in self.alternatives
        )

    @property
    def simple_field(self) -> str | None:
        if len(self.alternatives) == 1 and len(self.alternatives[0]) == 1:
            return self.alternatives[0][0]
        return None


@dataclass(frozen=True)
class ChannelSetupSpec:
    """Save, display, and validation contract for one channel."""

    fields: dict[str, ChannelFieldSpec]
    required: tuple[SetupRequirement, ...] = ()
    official_url: str | None = None

    @property
    def secrets(self) -> frozenset[str]:
        return frozenset(name for name, field in self.fields.items() if field.kind == "secret")

    @property
    def snapshot_fields(self) -> tuple[str, ...]:
        return tuple(name for name, field in self.fields.items() if field.snapshot)

    @property
    def route_field_types(self) -> dict[str, RouteFieldType]:
        return {
            name: field.route_type
            for name, field in self.fields.items()
            if field.writable
        }

    @property
    def simple_required_fields(self) -> tuple[str, ...]:
        return tuple(
            field
            for requirement in self.required
            if (field := requirement.simple_field) is not None
        )

    def is_configured(self, values: Any) -> bool:
        return bool(self.required) and all(
            requirement.is_satisfied(values) for requirement in self.required
        )


def _field(
    kind: FieldKind = "string",
    *,
    choices: set[str] | None = None,
    writable: bool = True,
    snapshot: bool = True,
) -> ChannelFieldSpec:
    return ChannelFieldSpec(
        kind=kind,
        choices=frozenset(choices or ()),
        writable=writable,
        snapshot=snapshot,
    )


def _required(field: str) -> SetupRequirement:
    return SetupRequirement(((field,),))


def _one_of(*alternatives: tuple[str, ...]) -> SetupRequirement:
    return SetupRequirement(alternatives)


_GROUP_POLICIES = {"mention", "open", "allowlist"}
_DIRECT_GROUP_POLICIES = {"mention", "open"}

CHANNEL_SETUP_SPECS: dict[str, ChannelSetupSpec] = {
    "websocket": ChannelSetupSpec(
        fields={},
        official_url="http://127.0.0.1:8765",
    ),
    "telegram": ChannelSetupSpec(
        fields={
            "token": _field("secret"),
            "allowFrom": _field("list"),
            "groupPolicy": _field("enum", choices=_GROUP_POLICIES),
        },
        required=(_required("token"),),
        official_url="https://t.me/BotFather",
    ),
    "slack": ChannelSetupSpec(
        fields={
            "appToken": _field("secret"),
            "botToken": _field("secret"),
            "groupPolicy": _field("enum", choices=_GROUP_POLICIES),
        },
        required=(_required("appToken"), _required("botToken")),
        official_url="https://api.slack.com/apps",
    ),
    "discord": ChannelSetupSpec(
        fields={
            "token": _field("secret"),
            "allowFrom": _field("list", snapshot=False),
            "allowChannels": _field("list"),
            "groupPolicy": _field("enum", choices=_DIRECT_GROUP_POLICIES),
        },
        required=(_required("token"),),
        official_url="https://discord.com/developers/applications",
    ),
    "email": ChannelSetupSpec(
        fields={
            "consentGranted": _field("bool"),
            "imapHost": _field(),
            "imapPort": _field("int"),
            "imapUsername": _field(),
            "imapPassword": _field("secret"),
            "smtpHost": _field(),
            "smtpPort": _field("int"),
            "smtpUsername": _field(),
            "smtpPassword": _field("secret"),
            "fromAddress": _field(),
            "pollIntervalSeconds": _field("int"),
            "allowFrom": _field("list"),
            "verifyDkim": _field("bool"),
            "verifySpf": _field("bool"),
        },
        required=tuple(
            _required(field)
            for field in (
                "consentGranted",
                "imapHost",
                "imapUsername",
                "imapPassword",
                "smtpHost",
                "smtpUsername",
                "smtpPassword",
            )
        ),
        official_url="https://support.google.com/accounts/answer/185833",
    ),
    "matrix": ChannelSetupSpec(
        fields={
            "homeserver": _field(),
            "userId": _field(),
            "password": _field("secret"),
            "accessToken": _field("secret"),
            "deviceId": _field(),
            "groupPolicy": _field("enum", choices=_GROUP_POLICIES),
            "allowFrom": _field("list", writable=False),
        },
        required=(
            _required("homeserver"),
            _required("userId"),
            _one_of(("password",), ("accessToken", "deviceId")),
        ),
        official_url="https://matrix.org/ecosystem/clients/",
    ),
    "mattermost": ChannelSetupSpec(
        fields={
            "serverUrl": _field(),
            "token": _field("secret"),
            "teamId": _field(),
            "groupPolicy": _field("enum", choices=_GROUP_POLICIES),
            "allowFrom": _field("list"),
        },
        required=(_required("serverUrl"), _required("token")),
        official_url="https://developers.mattermost.com/integrate/reference/bot-accounts/",
    ),
    "whatsapp": ChannelSetupSpec(
        fields={
            "allowFrom": _field("list", snapshot=False),
            "groupPolicy": _field("enum", choices=_DIRECT_GROUP_POLICIES, snapshot=False),
            "databasePath": _field(writable=False, snapshot=False),
        },
        official_url="https://faq.whatsapp.com/",
    ),
    "dingtalk": ChannelSetupSpec(
        fields={
            "clientId": _field(),
            "clientSecret": _field("secret"),
            "allowFrom": _field("list"),
        },
        required=(_required("clientId"), _required("clientSecret")),
        official_url="https://open.dingtalk.com/",
    ),
    "wecom": ChannelSetupSpec(
        fields={
            "botId": _field(),
            "secret": _field("secret"),
            "allowFrom": _field("list"),
        },
        required=(_required("botId"), _required("secret")),
        official_url="https://developer.work.weixin.qq.com/",
    ),
    "weixin": ChannelSetupSpec(
        fields={
            "token": _field("secret"),
            "allowFrom": _field("list"),
        },
        required=(_required("token"),),
        official_url="https://weixin.qq.com/",
    ),
    "qq": ChannelSetupSpec(
        fields={
            "appId": _field(),
            "secret": _field("secret"),
            "allowFrom": _field("list"),
            "msgFormat": _field("enum", choices={"plain", "markdown"}),
        },
        required=(_required("appId"), _required("secret")),
        official_url="https://q.qq.com/",
    ),
    "signal": ChannelSetupSpec(
        fields={
            "phoneNumber": _field(),
            "daemonHost": _field(),
            "daemonPort": _field("int"),
            "allowFrom": _field("list", snapshot=False),
            "dm.allowFrom": _field("list"),
            "group.allowFrom": _field("list"),
        },
        required=(_required("phoneNumber"),),
        official_url="https://github.com/bbernhard/signal-cli-rest-api",
    ),
    "msteams": ChannelSetupSpec(
        fields={
            "appId": _field(),
            "appPassword": _field("secret"),
            "tenantId": _field(),
            "path": _field(),
            "allowFrom": _field("list"),
        },
        required=(_required("appId"), _required("appPassword")),
        official_url="https://dev.teams.microsoft.com/apps",
    ),
    "napcat": ChannelSetupSpec(
        fields={
            "wsUrl": _field(),
            "accessToken": _field("secret"),
            "allowFrom": _field("list"),
            "groupPolicy": _field("enum", choices=_DIRECT_GROUP_POLICIES),
        },
        required=(_required("wsUrl"),),
        official_url="https://napneko.github.io/",
    ),
    "feishu": ChannelSetupSpec(
        fields={
            "appId": _field(snapshot=False),
            "appSecret": _field("secret", snapshot=False),
            "domain": _field("enum", choices={"feishu", "lark"}, snapshot=False),
            "groupPolicy": _field(
                "enum", choices=_DIRECT_GROUP_POLICIES, snapshot=False
            ),
            "allowFrom": _field("list", snapshot=False),
            "topicIsolation": _field("bool", snapshot=False),
        },
        required=(_required("appId"), _required("appSecret")),
        official_url="https://open.feishu.cn/app",
    ),
}


def channel_setup_spec(name: str) -> ChannelSetupSpec | None:
    return CHANNEL_SETUP_SPECS.get(name)


def channel_field_value(values: Any, field_path: str) -> Any:
    current = values
    for part in field_path.split("."):
        candidates = (part, _camel_to_snake(part))
        if isinstance(current, dict):
            for candidate in candidates:
                if candidate in current:
                    current = current[candidate]
                    break
            else:
                return None
            continue
        for candidate in candidates:
            if hasattr(current, candidate):
                current = getattr(current, candidate)
                break
        else:
            return None
    return current


def channel_value_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def stringify_channel_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char.isupper():
            if chars:
                chars.append("_")
            chars.append(char.lower())
        else:
            chars.append(char)
    return "".join(chars)
