"""Built-in channel registry entries."""

from __future__ import annotations

from nanobot.channels.registry import ChannelRegistry, ChannelSpec
from nanobot.config.schema import Config


def _groq_extra_kwargs(config: Config) -> dict[str, str]:
    return {"groq_api_key": config.providers.groq.api_key}


def _build_builtin_channel_registry() -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register(
        ChannelSpec(
            name="telegram",
            module_path="nanobot.channels.telegram",
            class_name="TelegramChannel",
            display_name="Telegram",
            extra_kwargs_factory=_groq_extra_kwargs,
        )
    )
    registry.register(
        ChannelSpec(
            name="whatsapp",
            module_path="nanobot.channels.whatsapp",
            class_name="WhatsAppChannel",
            display_name="WhatsApp",
        )
    )
    registry.register(
        ChannelSpec(
            name="discord",
            module_path="nanobot.channels.discord",
            class_name="DiscordChannel",
            display_name="Discord",
        )
    )
    registry.register(
        ChannelSpec(
            name="feishu",
            module_path="nanobot.channels.feishu",
            class_name="FeishuChannel",
            display_name="Feishu",
            extra_kwargs_factory=_groq_extra_kwargs,
        )
    )
    registry.register(
        ChannelSpec(
            name="mochat",
            module_path="nanobot.channels.mochat",
            class_name="MochatChannel",
            display_name="Mochat",
        )
    )
    registry.register(
        ChannelSpec(
            name="dingtalk",
            module_path="nanobot.channels.dingtalk",
            class_name="DingTalkChannel",
            display_name="DingTalk",
        )
    )
    registry.register(
        ChannelSpec(
            name="email",
            module_path="nanobot.channels.email",
            class_name="EmailChannel",
            display_name="Email",
        )
    )
    registry.register(
        ChannelSpec(
            name="slack",
            module_path="nanobot.channels.slack",
            class_name="SlackChannel",
            display_name="Slack",
        )
    )
    registry.register(
        ChannelSpec(
            name="qq",
            module_path="nanobot.channels.qq",
            class_name="QQChannel",
            display_name="QQ",
        )
    )
    registry.register(
        ChannelSpec(
            name="matrix",
            module_path="nanobot.channels.matrix",
            class_name="MatrixChannel",
            display_name="Matrix",
        )
    )
    return registry


BUILTIN_CHANNEL_REGISTRY = _build_builtin_channel_registry()
