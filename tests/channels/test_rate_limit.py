"""Tests for the per-sender channel rate limiter."""

from __future__ import annotations

from nanobot.channels.rate_limit import RateLimiter, format_cooldown_reply


class TestRateLimiterDisabled:
    def test_disabled_by_default(self) -> None:
        limiter = RateLimiter()
        assert limiter.enabled is False
        for _ in range(1000):
            assert limiter.check("user") is None

    def test_zero_per_minute_disables(self) -> None:
        limiter = RateLimiter(per_minute=0, burst=5)
        assert limiter.enabled is False
        assert limiter.check("user") is None


class TestRateLimiterPerMinute:
    def test_allows_up_to_the_limit(self) -> None:
        limiter = RateLimiter(per_minute=3)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        assert limiter.check("user", now=now + 1) is None
        assert limiter.check("user", now=now + 2) is None

    def test_rejects_once_limit_is_exceeded(self) -> None:
        limiter = RateLimiter(per_minute=3)
        now = 1000.0
        for i in range(3):
            assert limiter.check("user", now=now + i) is None
        retry_after = limiter.check("user", now=now + 3)
        assert retry_after is not None
        assert retry_after > 0

    def test_window_slides_and_recovers(self) -> None:
        limiter = RateLimiter(per_minute=2)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        assert limiter.check("user", now=now + 1) is None
        # Still within the 60s window from `now`, so this is rejected.
        retry_after = limiter.check("user", now=now + 30)
        assert retry_after is not None
        # After the first hit ages out of the 60s window, a new message fits.
        assert limiter.check("user", now=now + 61) is None

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter(per_minute=1)
        now = 1000.0
        assert limiter.check("alice", now=now) is None
        assert limiter.check("bob", now=now) is None
        assert limiter.check("alice", now=now + 1) is not None
        assert limiter.check("bob", now=now + 1) is not None

    def test_rejected_attempt_does_not_extend_the_window(self) -> None:
        limiter = RateLimiter(per_minute=1)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        # Rejected attempts must not be recorded, or the window would never
        # recover for a sender who keeps retrying while still blocked.
        assert limiter.check("user", now=now + 10) is not None
        assert limiter.check("user", now=now + 61) is None


class TestRateLimiterBurst:
    def test_burst_limit_applies_within_short_window(self) -> None:
        limiter = RateLimiter(per_minute=100, burst=2, burst_window_s=10)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        assert limiter.check("user", now=now + 1) is None
        # Third message within the 10s burst window is rejected even though
        # the per-minute budget of 100 is nowhere close to being hit.
        retry_after = limiter.check("user", now=now + 2)
        assert retry_after is not None

    def test_burst_limit_recovers_after_window(self) -> None:
        limiter = RateLimiter(per_minute=100, burst=2, burst_window_s=10)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        assert limiter.check("user", now=now + 1) is None
        assert limiter.check("user", now=now + 11) is None

    def test_none_burst_disables_burst_check(self) -> None:
        limiter = RateLimiter(per_minute=100, burst=None)
        now = 1000.0
        for i in range(10):
            assert limiter.check("user", now=now + i * 0.1) is None


class TestRateLimiterReset:
    def test_reset_single_key(self) -> None:
        limiter = RateLimiter(per_minute=1)
        now = 1000.0
        assert limiter.check("user", now=now) is None
        assert limiter.check("user", now=now + 1) is not None
        limiter.reset("user")
        assert limiter.check("user", now=now + 1) is None

    def test_reset_all_keys(self) -> None:
        limiter = RateLimiter(per_minute=1)
        now = 1000.0
        assert limiter.check("alice", now=now) is None
        assert limiter.check("bob", now=now) is None
        limiter.reset()
        assert limiter.check("alice", now=now) is None
        assert limiter.check("bob", now=now) is None


class TestFormatCooldownReply:
    def test_rounds_and_pluralizes(self) -> None:
        assert "1 second" in format_cooldown_reply(0.6)
        assert "5 seconds" in format_cooldown_reply(4.6)

    def test_never_reports_zero_or_negative(self) -> None:
        assert "1 second" in format_cooldown_reply(0.0)
        assert "1 second" in format_cooldown_reply(-5.0)
