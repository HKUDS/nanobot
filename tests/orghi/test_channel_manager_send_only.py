"""Tests for ChannelManager send_only behavior (orghi custom feature)."""

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from tests.orghi.conftest import RecordingChannel


@pytest.fixture
def manager(bus: MessageBus) -> ChannelManager:
    return ChannelManager(Config(), bus)


@pytest.mark.asyncio
async def test_start_channel_send_only_telegram_calls_start_with_send_only(
    manager: ChannelManager,
    recording_telegram: RecordingChannel,
) -> None:
    manager.channels["telegram"] = recording_telegram

    await manager._start_channel("telegram", recording_telegram, send_only=True)

    assert len(recording_telegram.start_calls) == 1
    _, kwargs = recording_telegram.start_calls[0]
    assert kwargs == {"send_only": True}


@pytest.mark.asyncio
async def test_start_channel_send_only_non_telegram_calls_start_without_args(
    manager: ChannelManager,
    recording_discord: RecordingChannel,
) -> None:
    manager.channels["discord"] = recording_discord

    await manager._start_channel("discord", recording_discord, send_only=True)

    assert len(recording_discord.start_calls) == 1
    _, kwargs = recording_discord.start_calls[0]
    assert kwargs == {}


@pytest.mark.asyncio
async def test_start_channel_no_send_only_calls_start_without_args(
    manager: ChannelManager,
    recording_telegram: RecordingChannel,
) -> None:
    manager.channels["telegram"] = recording_telegram

    await manager._start_channel(
        "telegram", recording_telegram, send_only=False
    )

    assert len(recording_telegram.start_calls) == 1
    _, kwargs = recording_telegram.start_calls[0]
    assert kwargs == {}


@pytest.mark.asyncio
async def test_start_for_cron_job_passes_send_only_to_all_channels(
    manager: ChannelManager,
    recording_telegram: RecordingChannel,
    recording_discord: RecordingChannel,
) -> None:
    manager.channels = {
        "telegram": recording_telegram,
        "discord": recording_discord,
    }

    await manager.start_for_cron_job()

    assert len(recording_telegram.start_calls) == 1
    assert recording_telegram.start_calls[0][1] == {"send_only": True}

    assert len(recording_discord.start_calls) == 1
    assert recording_discord.start_calls[0][1] == {}
