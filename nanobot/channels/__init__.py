"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.registry import ChannelRegistry, ChannelSpec

__all__ = ["BaseChannel", "ChannelManager", "ChannelRegistry", "ChannelSpec"]
