"""Smoke tests for DiscordChannel initialization and basic wiring."""

from __future__ import annotations

import pytest

discord = pytest.importorskip("discord")

from nanobot.bus.queue import MessageBus  # noqa: E402
from nanobot.channels.discord import DiscordChannel, DiscordConfig  # noqa: E402


def _make_channel() -> DiscordChannel:
    config = DiscordConfig(token="fake-token")
    bus = MessageBus()
    return DiscordChannel(config, bus)


def test_discord_channel_name():
    ch = _make_channel()
    assert ch.name == "discord"


def test_discord_channel_pending_interactions_starts_empty():
    ch = _make_channel()
    assert ch._pending_interactions == {}


def test_discord_channel_interaction_timestamps_starts_empty():
    ch = _make_channel()
    assert ch._interaction_timestamps == {}


def test_discord_channel_set_tool_registry():
    ch = _make_channel()
    mock_registry = object()
    ch.set_tool_registry(mock_registry)
    assert ch._tool_registry is mock_registry
