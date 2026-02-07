"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import spawn_channels

__all__ = ["BaseChannel", "spawn_channels"]
