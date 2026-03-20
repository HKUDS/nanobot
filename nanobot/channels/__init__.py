"""Chat channels module with plugin architecture."""

from __future__ import annotations

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.retry import ChannelHealth
from nanobot.channels.web import WebChannel

__all__ = ["BaseChannel", "ChannelHealth", "ChannelManager", "WebChannel"]
