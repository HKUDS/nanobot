"""Tests for the rolling-window rate limiter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_window_total_empty(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        assert rl.window_total() == 0

    def test_record_increases_total(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        rl.record(10_000)
        assert rl.window_total() == 10_000

    def test_multiple_records_sum(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        rl.record(10_000)
        rl.record(15_000)
        assert rl.window_total() == 25_000

    def test_old_entries_pruned(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        import time

        old_time = time.monotonic() - 61.0
        from nanobot.providers.rate_limiter import TokenRecord

        rl._window.append(TokenRecord(timestamp=old_time, tokens=30_000))
        rl.record(5_000)
        assert rl.window_total() == 5_000

    @pytest.mark.asyncio
    async def test_wait_if_needed_under_threshold_no_sleep(self):
        rl = RateLimiter(tokens_per_minute=50_000, threshold=0.80)
        rl.record(30_000)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited == 0.0
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_if_needed_over_threshold_sleeps(self):
        rl = RateLimiter(tokens_per_minute=50_000, threshold=0.80)
        rl.record(45_000)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited > 0.0
        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert 1.0 <= sleep_arg <= 15.0

    @pytest.mark.asyncio
    async def test_wait_if_needed_empty_window_no_sleep(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited == 0.0
        mock_sleep.assert_not_called()

    def test_threshold_boundary_exact(self):
        rl = RateLimiter(tokens_per_minute=100, threshold=0.80)
        rl.record(79)
        assert rl.window_total() == 79

    def test_default_threshold(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        assert rl._threshold == 0.80
