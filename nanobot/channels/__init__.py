"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import get_channel_actor, spawn_channels

__all__ = ["BaseChannel", "get_channel_actor", "spawn_channels"]
