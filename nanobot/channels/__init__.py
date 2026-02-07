"""Chat channels module with plugin architecture."""

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import create_channels, spawn_channel_actors

__all__ = ["BaseChannel", "create_channels", "spawn_channel_actors"]
