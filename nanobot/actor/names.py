"""Centralized actor names and naming helpers.

Avoid scattering magic strings like "agent" / "provider" / "scheduler" and
"channel.{name}" across the codebase. This makes renaming and multi-instance
namespacing much easier.
"""

DEFAULT_AGENT_NAME = "agent"
DEFAULT_PROVIDER_NAME = "provider"
DEFAULT_SCHEDULER_NAME = "scheduler"


def channel_actor_name(channel: str) -> str:
    """Return the Pulsing actor name for a channel."""
    return f"channel.{channel}"

