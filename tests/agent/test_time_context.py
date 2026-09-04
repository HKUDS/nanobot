"""Tests for the built-in current-time runtime context provider (#5645)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from nanobot.agent.time_context import (
    TIME_CONTEXT_SOURCE,
    current_time_provider,
    current_time_str,
)


class TestCurrentTimeStr:
    def test_explicit_timezone_is_used(self):
        result = current_time_str("Europe/Berlin")
        assert "Europe/Berlin" in result
        assert "UTC+" in result or "UTC-" in result

    def test_invalid_timezone_falls_back_to_local(self):
        # Must not raise; falls back to local time.
        result = current_time_str("Not/AZone")
        assert "Current" not in result  # sanity: this is the raw time string
        assert len(result) > 0

    def test_format_matches_pre_4891_shape(self):
        result = current_time_str("UTC")
        # YYYY-MM-DD HH:MM (Weekday) (TZ, UTC±HH:MM)
        assert "(" in result and ")" in result
        assert "UTC+00:00" in result


class TestCurrentTimeProvider:
    def test_provider_returns_block(self):
        provider = current_time_provider("Europe/Berlin")
        blocks = asyncio.run(provider(object()))
        assert len(blocks) == 1
        assert blocks[0].source == TIME_CONTEXT_SOURCE
        assert "Current Time:" in blocks[0].content
        assert "Europe/Berlin" in blocks[0].content

    def test_content_is_delimited(self):
        provider = current_time_provider(None)
        blocks = asyncio.run(provider(object()))
        assert blocks[0].content.startswith("[Runtime Context")
        assert blocks[0].content.endswith("[/Runtime Context]")


class TestAgentLoopRegistration:
    @staticmethod
    def _make_loop(tmp_path, **extra):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        return AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            **extra,
        )

    def test_loop_registers_provider_when_timezone_configured(self, tmp_path):
        loop = self._make_loop(tmp_path, timezone="Europe/Berlin")
        assert len(loop._runtime_context_providers) >= 1

    def test_loop_skips_registration_without_timezone(self, tmp_path):
        loop = self._make_loop(tmp_path)
        assert len(loop._runtime_context_providers) == 0

    @pytest.mark.asyncio
    async def test_registered_provider_surfaces_current_time_block(self, tmp_path):
        loop = self._make_loop(tmp_path, timezone="Europe/Berlin")
        blocks = await loop._resolve_runtime_context_for_request(
            request=type(
                "R",
                (),
                {
                    "metadata": {},
                    "original_user_text": "",
                    "session_key": "test-session",
                    "workspace": None,
                },
            )(),
            tools=loop.tools,
        )
        assert any(
            b.source == TIME_CONTEXT_SOURCE and "Europe/Berlin" in b.content
            for b in blocks
        )
