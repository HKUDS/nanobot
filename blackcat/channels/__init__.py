"""Chat channels module with plugin architecture."""

from blackcat.channels.base import BaseChannel
from blackcat.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
