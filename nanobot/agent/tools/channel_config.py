"""Agent tool for safely updating NanoBot chat channel config."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    BooleanSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)


def _mask_channel_secrets(value: Any) -> Any:
    """Redact obvious secret fields before echoing config back to the model."""
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, inner in value.items():
            lowered = key.lower()
            if any(
                term in lowered for term in ("token", "secret", "password", "api_key", "apikey")
            ):
                masked[key] = "***"
            else:
                masked[key] = _mask_channel_secrets(inner)
        return masked
    if isinstance(value, list):
        return [_mask_channel_secrets(item) for item in value]
    return value


@tool_parameters(
    tool_parameters_schema(
        channel=StringSchema("Channel name such as telegram, discord, slack, or email."),
        enabled=BooleanSchema(
            description="Whether the channel should be enabled after this update.",
            nullable=True,
        ),
        settings=ObjectSchema(
            description=(
                "Partial channel settings to merge into the selected channel config. "
                "Keys may use snake_case or camelCase."
            ),
            additional_properties=True,
            nullable=True,
        ),
        required=["channel"],
    )
)
class ConfigureChannelTool(Tool):
    """Update `channels.<name>` inside NanoBot's config file."""

    @property
    def name(self) -> str:
        return "configure_channel"

    @property
    def description(self) -> str:
        return (
            "Update NanoBot chat channel config in config.json. Use this when the user wants "
            "NanoBot to listen on a configured channel, including AgentHiFive-managed channels "
            "under channels.agenthifive. "
            "After using it, tell the user to restart `nanobot gateway`."
        )

    async def execute(
        self,
        channel: str | None = None,
        enabled: bool | None = None,
        settings: dict[str, Any] | None = None,
        **_: Any,
    ) -> str:
        from nanobot.cli import onboard
        from nanobot.config.loader import get_config_path, load_config, save_config, set_config_path

        channel_name = (channel or "").strip().lower()
        if not channel_name:
            return "Error: channel is required"

        available = onboard._get_channel_names()
        if channel_name not in available:
            choices = ", ".join(sorted(available))
            return f"Error: Unknown channel '{channel_name}'. Available channels: {choices}"

        config_cls = onboard._get_channel_config_class(channel_name)
        if config_cls is None:
            return f"Error: No config schema is available for channel '{channel_name}'"

        config_path = get_config_path().expanduser().resolve()
        set_config_path(config_path)
        loaded = load_config(config_path)
        existing = getattr(loaded.channels, channel_name, None) or {}

        merged = dict(existing)
        if settings:
            merged.update(settings)
        if enabled is not None:
            merged["enabled"] = enabled

        try:
            validated = config_cls.model_validate(merged)
        except Exception as exc:
            return f"Error: Invalid {channel_name} channel settings: {exc}"

        setattr(
            loaded.channels,
            channel_name,
            validated.model_dump(by_alias=True, exclude_none=True),
        )
        save_config(loaded, config_path)

        saved_section = _mask_channel_secrets(getattr(loaded.channels, channel_name, None) or {})
        return (
            f"Updated NanoBot channel '{channel_name}' in {config_path}. "
            "Restart `nanobot gateway` for the change to take effect. "
            f"Saved settings: {saved_section}"
        )
