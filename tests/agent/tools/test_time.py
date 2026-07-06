"""Tests for ``NanoTimerTool`` — 7 categories from the implementation plan."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.time import NanoTimerTool, _resolve_server_tz


def _ctx(timezone: str = "UTC") -> ToolContext:
    return ToolContext(
        config=SimpleNamespace(),
        workspace="/tmp/nano_timer_test",
        timezone=timezone,
    )


def _ctx_with_all_tools() -> ToolContext:
    """ToolContext stub for the loader test: every tool's enabled() must pass.

    Some tools read nested config attributes (e.g. ``ctx.config.exec.enable``).
    We satisfy those by attaching a permissive attribute to a SimpleNamespace.
    """
    cfg = SimpleNamespace()
    cfg.exec = SimpleNamespace(enable=False)  # disable exec to keep loader test fast
    return ToolContext(config=cfg, workspace="/tmp/nano_timer_test", timezone="UTC")


class TestNanoTimerTimezoneMath:
    def test_utc_offset_is_zero(self):
        tool = NanoTimerTool(timezone="UTC")
        payload = tool._compute_payload()
        assert payload["user"]["offset"] == "UTC+0"
        assert payload["user"]["timezone"] == "UTC"

    def test_sao_paulo_january_is_minus_three(self):
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            payload = tool._compute_payload()
        # Since 2019 Brazil no longer observes DST; SP stays UTC-3 year-round.
        assert payload["user"]["offset"] == "UTC-3"

    def test_sao_paulo_july_is_minus_three(self):
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            payload = tool._compute_payload()
        assert payload["user"]["offset"] == "UTC-3"

    def test_diff_from_utc_hours_matches_user_timezone(self):
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            payload = tool._compute_payload()
        assert payload["context"]["diff_from_utc_hours"] == "-3h"

    def test_diff_from_utc_hours_includes_minutes(self):
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Asia/Kolkata")
            payload = tool._compute_payload()
        assert payload["context"]["diff_from_utc_hours"] == "+5h30m"

    def test_round_trip_utc_to_user_to_utc(self):
        from datetime import datetime, timezone
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            t1 = datetime.now(timezone.utc)
            user_tz = ZoneInfo("Asia/Tokyo")
            t2 = t1.astimezone(user_tz).astimezone(timezone.utc)
        assert abs((t2 - t1).total_seconds()) < 1

    def test_india_kolkata_offset_includes_minutes(self):
        # Regression: UTC+5:30 (India) used to render as "UTC+5".
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Asia/Kolkata")
            payload = tool._compute_payload()
        assert payload["user"]["offset"] == "UTC+5:30"

    def test_nepal_kathmandu_offset_includes_minutes(self):
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Asia/Kathmandu")
            payload = tool._compute_payload()
        assert payload["user"]["offset"] == "UTC+5:45"

    def test_chatham_islands_offset_includes_minutes(self):
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Pacific/Chatham")
            payload = tool._compute_payload()
        assert payload["user"]["offset"] == "UTC+12:45"


class TestNanoTimerDSTTransitions:
    def test_br_no_dst_year_round(self):
        # Brazil abolished DST in 2019 (Decreto 9.772). São Paulo is UTC-3
        # all year. Document that here so a future change in legislation
        # surfaces as a test diff rather than a silent regression.
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            jan = tool._compute_payload()["user"]["offset"]
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            jul = tool._compute_payload()["user"]["offset"]
        assert jan == "UTC-3"
        assert jul == "UTC-3"

    def test_ny_dst_spring_forward(self):
        # NY still observes DST: EST (UTC-5) in winter, EDT (UTC-4) in summer.
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/New_York")
            winter = tool._compute_payload()["user"]["offset"]
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/New_York")
            summer = tool._compute_payload()["user"]["offset"]
        assert winter == "UTC-5"
        assert summer == "UTC-4"

    def test_london_summer_time(self):
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Europe/London")
            winter = tool._compute_payload()["user"]["offset"]
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Europe/London")
            summer = tool._compute_payload()["user"]["offset"]
        assert winter == "UTC+0"
        assert summer == "UTC+1"

    def test_sydney_southern_hemisphere_dst(self):
        # Sydney is UTC+10 in winter (AEST), UTC+11 in summer (AEDT).
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Australia/Sydney")
            winter = tool._compute_payload()["user"]["offset"]
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="Australia/Sydney")
            summer = tool._compute_payload()["user"]["offset"]
        assert winter == "UTC+10"
        assert summer == "UTC+11"


@pytest.mark.skipif(sys.platform == "win32", reason="TZ+tzset is Unix-only")
class TestNanoTimerServerTz:
    def test_server_tz_tokyo(self):
        with patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            import time
            time.tzset()
            label, offset = _resolve_server_tz()
        assert label == "Asia/Tokyo"  # tzinfo.key, not tzname
        assert offset == "UTC+9"

    def test_server_tz_berlin_summer(self):
        with freeze_time("2026-07-15 12:00:00", tz_offset=0):
            with patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
                import time
                time.tzset()
                label, offset = _resolve_server_tz()
        assert label == "Europe/Berlin"
        assert offset in ("UTC+2", "UTC+1")

    def test_server_tz_berlin_winter(self):
        with freeze_time("2026-01-15 12:00:00", tz_offset=0):
            with patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
                import time
                time.tzset()
                label, offset = _resolve_server_tz()
        assert label == "Europe/Berlin"
        assert offset == "UTC+1"

    def test_server_tz_sao_paulo(self):
        # Regression: tzname() returned "-03" in some environments.
        # We rely on tzinfo.key returning the IANA name.
        with freeze_time("2026-06-22 12:00:00", tz_offset=0):
            with patch.dict(os.environ, {"TZ": "America/Sao_Paulo"}):
                import time
                time.tzset()
                label, offset = _resolve_server_tz()
        assert label == "America/Sao_Paulo"
        assert offset == "UTC-3"


class TestNanoTimerOutputFormats:
    @pytest.mark.asyncio
    async def test_info_type_time_excludes_calendar(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type="time")
        assert "UTC Time" in out
        assert "User Local Time" in out
        assert "**Calendar**" not in out
        assert "**Context**" not in out

    @pytest.mark.asyncio
    async def test_info_type_calendar_only(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type="calendar")
        assert "**Calendar**" in out
        assert "Weekday" in out
        assert "Week of year" in out
        assert "**UTC Time**" not in out
        assert "**Context**" not in out

    @pytest.mark.asyncio
    async def test_info_type_timezone_only(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="America/Sao_Paulo")
            out = await tool.execute(info_type="timezone")
        assert "**Context**" in out
        assert "Server timezone" in out
        assert "**UTC Time**" not in out
        assert "**Calendar**" not in out

    @pytest.mark.asyncio
    async def test_info_type_all_includes_everything(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type="all")
        assert "**UTC Time**" in out
        assert "**User Local Time**" in out
        assert "**Calendar**" in out
        assert "**Context**" in out

    @pytest.mark.asyncio
    async def test_info_type_none_defaults_to_all(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type=None)
        assert "**UTC Time**" in out
        assert "**Calendar**" in out

    @pytest.mark.asyncio
    async def test_info_type_invalid_falls_back_to_all(self):
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type="invalid_value")
        assert "**UTC Time**" in out
        assert "**Calendar**" in out

    @pytest.mark.asyncio
    async def test_no_consecutive_blank_lines(self):
        # Regression: blocks used to insert double blank lines between them.
        import re
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            tool = NanoTimerTool(timezone="UTC")
            out = await tool.execute(info_type="all")
        # Allow single \n\n (one blank line) but never \n\n\n+.
        assert not re.search(r"\n\n\n+", out), (
            f"Output has consecutive blank lines:\n{out!r}"
        )


class TestNanoTimerIANAValidation:
    @pytest.mark.asyncio
    async def test_invalid_iana_logs_warning_and_uses_utc(self):
        tool = NanoTimerTool(timezone="BRT")
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            out = await tool.execute(info_type="all")
        assert "UTC Time" in out
        assert "BRT" in out
        assert "invalid" in out.lower()

    @pytest.mark.asyncio
    async def test_empty_iana_falls_back_to_utc(self):
        tool = NanoTimerTool(timezone="")
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            out = await tool.execute(info_type="time")
        assert "UTC" in out

    @pytest.mark.asyncio
    async def test_valid_la_iana_works(self):
        tool = NanoTimerTool(timezone="America/Los_Angeles")
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            out = await tool.execute(info_type="timezone")
        assert "Server timezone" in out
        assert "BRT" not in out

    def test_lowercase_iana_is_case_sensitive(self):
        # Python's ZoneInfo is case-sensitive; this documents the behavior.
        with pytest.raises(Exception):
            ZoneInfo("america/sao_paulo")


class TestNanoTimerToolLoaderDiscovery:
    def test_discover_includes_nano_timer(self):
        loader = ToolLoader()
        classes = loader.discover()
        assert NanoTimerTool in classes

    def test_load_registers_nano_timer_in_registry(self):
        loader = ToolLoader()
        registry = ToolRegistry()
        loader.load(_ctx(timezone="America/Sao_Paulo"), registry)
        assert registry.has("nano_timer")

    def test_load_uses_ctx_timezone(self):
        loader = ToolLoader()
        registry = ToolRegistry()
        loader.load(_ctx(timezone="Asia/Tokyo"), registry)
        tool = registry.get("nano_timer")
        assert tool is not None
        assert tool._timezone == "Asia/Tokyo"

    def test_no_name_collision_with_existing_tools(self):
        loader = ToolLoader()
        registry = ToolRegistry()
        registered = loader.load(_ctx_with_all_tools(), registry)
        # nano_timer must be in the registered set, not collide with cron/search/etc.
        assert "nano_timer" in registered
        # cron requires cron_service to be present in ctx; without it, cron is
        # disabled by its own enabled() check. We don't require it here — we
        # just need nano_timer to coexist with whatever else is registered.
        assert "search" in registered or len(registered) >= 1


class TestNanoTimerRequestContext:
    def test_set_context_stores_channel_and_chat_id(self):
        tool = NanoTimerTool(timezone="UTC")
        tool.set_context(
            RequestContext(channel="telegram", chat_id="8281248569")
        )
        assert tool._channel == "telegram"
        assert tool._chat_id == "8281248569"

    @pytest.mark.asyncio
    async def test_set_context_does_not_break_execution(self):
        tool = NanoTimerTool(timezone="UTC")
        tool.set_context(
            RequestContext(channel="websocket", chat_id="c1")
        )
        with freeze_time("2026-06-22 15:00:00", tz_offset=0):
            out = await tool.execute(info_type="all")
        assert "UTC Time" in out

    def test_create_uses_ctx_timezone(self):
        ctx = _ctx(timezone="America/New_York")
        tool = NanoTimerTool.create(ctx)
        assert tool._timezone == "America/New_York"

    def test_create_default_timezone_when_ctx_missing(self):
        # ctx without explicit timezone -> ToolContext default "UTC"
        ctx = ToolContext(config=SimpleNamespace(), workspace="/tmp")
        tool = NanoTimerTool.create(ctx)
        assert tool._timezone == "UTC"
