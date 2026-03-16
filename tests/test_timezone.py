"""Tests for timezone consolidation — parse_user_timezone and current_time_str(tz_name)."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.utils.helpers import current_time_str, parse_user_timezone


# --- current_time_str tests ---


def test_current_time_str_no_arg_preserves_behavior() -> None:
    """Calling with no argument should return a string with weekday and timezone abbreviation."""
    result = current_time_str()
    # Should match pattern: YYYY-MM-DD HH:MM (Weekday) (TZ)
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(.+\)", result)


def test_current_time_str_valid_iana() -> None:
    """Valid IANA timezone should appear in the output."""
    result = current_time_str("Asia/Tokyo")
    assert "(Asia/Tokyo)" in result
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(Asia/Tokyo\)", result)


def test_current_time_str_invalid_fallback() -> None:
    """Invalid timezone should fallback to system timezone without crashing."""
    result = current_time_str("Invalid/Zone")
    # Should NOT contain "Invalid/Zone", should contain a system tz
    assert "Invalid/Zone" not in result
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(.+\)", result)


# --- parse_user_timezone tests ---


def test_parse_valid_iana(tmp_path: Path) -> None:
    """USER.md with valid IANA timezone should return the timezone string."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: Asia/Shanghai\n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) == "Asia/Shanghai"


def test_parse_placeholder_returns_none(tmp_path: Path) -> None:
    """USER.md with default placeholder should return None."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: (your timezone, e.g., Asia/Shanghai)\n",
        encoding="utf-8",
    )
    assert parse_user_timezone(tmp_path) is None


def test_parse_missing_file(tmp_path: Path) -> None:
    """Missing USER.md should return None."""
    assert parse_user_timezone(tmp_path) is None


def test_parse_invalid_tz_returns_none(tmp_path: Path) -> None:
    """USER.md with invalid timezone (e.g. UTC+8) should return None after ZoneInfo validation."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: UTC+8\n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) is None


def test_parse_empty_timezone_returns_none(tmp_path: Path) -> None:
    """USER.md with empty timezone field should return None."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: \n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) is None


def test_parse_indented_bullet(tmp_path: Path) -> None:
    """Indented markdown bullet should still be parsed."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n    - **Timezone**: Asia/Shanghai\n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) == "Asia/Shanghai"


def test_parse_asterisk_bullet(tmp_path: Path) -> None:
    """Asterisk bullet should also be parsed."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n* **Timezone**: Europe/London\n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) == "Europe/London"


# --- Integration tests ---


def test_runtime_context_uses_user_tz(tmp_path: Path) -> None:
    """ContextBuilder._build_runtime_context should use user timezone when provided."""
    from nanobot.agent.context import ContextBuilder

    result = ContextBuilder._build_runtime_context(
        channel="cli", chat_id="test", tz_name="Asia/Tokyo"
    )
    assert "(Asia/Tokyo)" in result
    assert "Current Time:" in result


@pytest.mark.asyncio
async def test_heartbeat_uses_cached_tz(tmp_path: Path) -> None:
    """HeartbeatService should parse timezone once and reuse on subsequent calls."""
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.providers.base import LLMProvider, LLMResponse

    # Write USER.md with valid timezone
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: America/New_York\n", encoding="utf-8"
    )
    (tmp_path / "HEARTBEAT.md").write_text("check tasks", encoding="utf-8")

    class FakeProvider(LLMProvider):
        def __init__(self):
            super().__init__()
            self.captured_messages: list[dict] = []

        def get_default_model(self) -> str:
            return "test"

        async def chat(self, *, messages=None, **kwargs) -> LLMResponse:
            if messages:
                self.captured_messages.extend(messages)
            return LLMResponse(
                content=None,
                tool_calls=[
                    type("TC", (), {
                        "id": "1",
                        "name": "heartbeat",
                        "arguments": {"action": "skip"},
                    })()
                ],
            )

    provider = FakeProvider()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test",
        enabled=False,
    )

    # First call: should parse timezone
    await service._decide("test heartbeat content")
    assert service._user_tz == "America/New_York"
    assert any("(America/New_York)" in str(m.get("content", "")) for m in provider.captured_messages)

    # Second call: should reuse cached timezone (no re-parsing)
    provider.captured_messages.clear()
    await service._decide("test heartbeat content 2")
    assert service._user_tz == "America/New_York"
    assert any("(America/New_York)" in str(m.get("content", "")) for m in provider.captured_messages)
