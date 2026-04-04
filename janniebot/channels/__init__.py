"""Chat channels module with plugin architecture."""

from janniebot.channels.base import BaseChannel
from janniebot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
