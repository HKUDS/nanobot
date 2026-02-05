"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager

# Channels are dynamically imported by ChannelManager
# to avoid import errors when dependencies are missing

__all__ = ["BaseChannel", "ChannelManager"]
