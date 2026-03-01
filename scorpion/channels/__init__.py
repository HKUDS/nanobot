"""Chat channels module with plugin architecture."""

from scorpion.channels.base import BaseChannel
from scorpion.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
