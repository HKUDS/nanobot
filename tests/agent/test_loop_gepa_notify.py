"""Tests for GEPA completion notifications on AgentLoop (E4-F2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.evolution.gepa_runner import GepaRunResult
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import EvolutionConfig, EvolutionGepaConfig


@pytest.mark.asyncio
async def test_run_gepa_publishes_outbound_when_slash_creates_proposals() -> None:
    published: list[OutboundMessage] = []
    bus = SimpleNamespace(
        publish_outbound=AsyncMock(
            side_effect=lambda message: published.append(message),
        ),
    )
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=GepaRunResult(
                phase="completed",
                proposals_created=("abcdef12-3456-7890",),
                message="1 GEPA proposal(s) ready",
            ),
        ),
    )
    loop = SimpleNamespace(
        bus=bus,
        _evolution=EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True)),
        _get_gepa_runner=lambda: runner,
    )

    await AgentLoop._run_gepa(
        loop,
        trigger="slash",
        notify_to=("telegram", "chat-99"),
    )

    assert len(published) == 1
    assert published[0].channel == "telegram"
    assert published[0].chat_id == "chat-99"
    assert "GEPA proposal ready" in published[0].content
    assert "abcdef12" in published[0].content


@pytest.mark.asyncio
async def test_run_gepa_skips_outbound_when_no_proposals() -> None:
    bus = SimpleNamespace(publish_outbound=AsyncMock())
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=GepaRunResult(phase="completed", proposals_created=()),
        ),
    )
    loop = SimpleNamespace(
        bus=bus,
        _evolution=EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True)),
        _get_gepa_runner=lambda: runner,
    )

    await AgentLoop._run_gepa(
        loop,
        trigger="slash",
        notify_to=("cli", "direct"),
    )

    bus.publish_outbound.assert_not_called()
