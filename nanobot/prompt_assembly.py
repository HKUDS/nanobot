"""Compose model context at the SDK, gateway and classic CLI entry points."""

from nanobot.agent.context import ContextBuilder
from nanobot.channels.registry import make_reply_format_resolver
from nanobot.config.schema import Config


def build_context_builder(config: Config, **local_formats: str) -> ContextBuilder:
    defaults = config.agents.defaults
    return ContextBuilder(
        config.workspace_path, timezone=defaults.timezone, disabled_skills=defaults.disabled_skills,
        reply_format_for=make_reply_format_resolver(**local_formats),
    )
