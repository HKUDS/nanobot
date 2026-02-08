"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager

# Optional A2A channel (requires a2a-sdk)
try:
    from nanobot.channels.a2a import A2AChannel
    A2A_CHANNEL_AVAILABLE = True
except ImportError:
    A2AChannel = None  # type: ignore
    A2A_CHANNEL_AVAILABLE = False

__all__ = ["BaseChannel", "ChannelManager", "A2AChannel", "A2A_CHANNEL_AVAILABLE"]
