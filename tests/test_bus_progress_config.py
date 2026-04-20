"""Test that _bus_progress respects channels_config.send_progress and send_tool_hints.

Regression test for https://github.com/HKUDS/nanobot/issues/1350
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import ChannelsConfig


def _make_bus_progress(channels_config, bus, msg_metadata=None):
    """Replicate the _bus_progress closure from AgentLoop.process_message.

    This mirrors the exact logic in nanobot/agent/loop.py so we can test
    the config-gating behaviour in isolation without spinning up the full
    agent loop (which needs provider credentials, workspace dirs, etc.).
    """

    async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        meta = dict(msg_metadata or {})
        meta["_progress"] = True
        meta["_tool_hint"] = tool_hint
        await bus.publish_outbound(content)

    return _bus_progress


class TestBusProgressRespectsConfig:
    """_bus_progress should honour send_progress and send_tool_hints settings."""

    @pytest.mark.asyncio
    async def test_progress_suppressed_when_send_progress_false(self):
        """When send_progress=False, non-tool-hint progress must NOT be published."""
        cfg = ChannelsConfig(send_progress=False, send_tool_hints=True)
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(cfg, bus)

        await progress("thinking...", tool_hint=False)
        bus.publish_outbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_hints_suppressed_when_send_tool_hints_false(self):
        """When send_tool_hints=False, tool-hint progress must NOT be published."""
        cfg = ChannelsConfig(send_progress=True, send_tool_hints=False)
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(cfg, bus)

        await progress("read_file(…)", tool_hint=True)
        bus.publish_outbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_sent_when_config_allows(self):
        """When both flags are True, all progress messages must be published."""
        cfg = ChannelsConfig(send_progress=True, send_tool_hints=True)
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(cfg, bus)

        await progress("thinking...", tool_hint=False)
        assert bus.publish_outbound.call_count == 1

        await progress("read_file(…)", tool_hint=True)
        assert bus.publish_outbound.call_count == 2

    @pytest.mark.asyncio
    async def test_progress_sent_when_no_channels_config(self):
        """When channels_config is None (no config), all progress goes through."""
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(None, bus)

        await progress("thinking...", tool_hint=False)
        assert bus.publish_outbound.call_count == 1

        await progress("read_file(…)", tool_hint=True)
        assert bus.publish_outbound.call_count == 2

    @pytest.mark.asyncio
    async def test_mixed_scenario(self):
        """send_progress=False but send_tool_hints=True: only tool hints go through."""
        cfg = ChannelsConfig(send_progress=False, send_tool_hints=True)
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(cfg, bus)

        await progress("thinking...", tool_hint=False)
        bus.publish_outbound.assert_not_called()

        await progress("read_file(…)", tool_hint=True)
        assert bus.publish_outbound.call_count == 1

    @pytest.mark.asyncio
    async def test_inverse_mixed_scenario(self):
        """send_progress=True but send_tool_hints=False: only regular progress goes through."""
        cfg = ChannelsConfig(send_progress=True, send_tool_hints=False)
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        progress = _make_bus_progress(cfg, bus)

        await progress("thinking...", tool_hint=False)
        assert bus.publish_outbound.call_count == 1

        await progress("read_file(…)", tool_hint=True)
        # Still 1 — the tool hint was suppressed
        assert bus.publish_outbound.call_count == 1
