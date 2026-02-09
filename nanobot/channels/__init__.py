"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.moltchat import MoltchatChannel

__all__ = ["BaseChannel", "ChannelManager", "MoltchatChannel"]
