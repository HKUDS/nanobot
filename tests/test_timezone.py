"""Tests for timezone configuration — config.json + USER.md deprecation fallback."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.utils.helpers import current_time_str, parse_user_timezone


# --- current_time_str tests ---


def test_current_time_str_no_arg_preserves_behavior() -> None:
    """Calling with no argument should return a string with weekday and timezone abbreviation."""
    result = current_time_str()
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(.+\)", result)


def test_current_time_str_valid_iana() -> None:
    """Valid IANA timezone should appear in the output."""
    result = current_time_str("Asia/Tokyo")
    assert "(Asia/Tokyo)" in result
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(Asia/Tokyo\)", result)


def test_current_time_str_invalid_fallback() -> None:
    """Invalid timezone should fallback to system timezone without crashing."""
    result = current_time_str("Invalid/Zone")
    assert "Invalid/Zone" not in result
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\w+\) \(.+\)", result)


# --- parse_user_timezone tests (kept for deprecation fallback) ---


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


def test_parse_asterisk_bullet(tmp_path: Path) -> None:
    """Asterisk bullet should also be parsed."""
    (tmp_path / "USER.md").write_text(
        "# User Profile\n* **Timezone**: Europe/London\n", encoding="utf-8"
    )
    assert parse_user_timezone(tmp_path) == "Europe/London"


# --- Config-based integration tests ---


def test_runtime_context_uses_config_timezone() -> None:
    """ContextBuilder._build_runtime_context should use config timezone."""
    from nanobot.agent.context import ContextBuilder

    result = ContextBuilder._build_runtime_context(
        channel="cli", chat_id="test", tz_name="Asia/Tokyo"
    )
    assert "(Asia/Tokyo)" in result
    assert "Current Time:" in result


def test_runtime_context_no_timezone_uses_system() -> None:
    """ContextBuilder._build_runtime_context with tz_name=None uses system time."""
    from nanobot.agent.context import ContextBuilder

    result = ContextBuilder._build_runtime_context(channel="cli", chat_id="test", tz_name=None)
    assert "Current Time:" in result
    # Should NOT contain any IANA timezone path
    assert "/" not in result.split("Current Time:")[1].split("\n")[0] or "Asia/" not in result


def test_context_builder_passes_timezone(tmp_path: Path) -> None:
    """ContextBuilder stores timezone and passes it to _build_runtime_context."""
    from nanobot.agent.context import ContextBuilder

    # Create minimal workspace
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")

    ctx = ContextBuilder(tmp_path, timezone="Asia/Shanghai")
    assert ctx.timezone == "Asia/Shanghai"


def test_config_schema_timezone_field() -> None:
    """Config schema accepts timezone field without crashing."""
    from nanobot.config.schema import Config

    config = Config.model_validate({
        "agents": {"defaults": {"timezone": "America/New_York"}}
    })
    assert config.agents.defaults.timezone == "America/New_York"


def test_config_schema_timezone_none_default() -> None:
    """Config without timezone defaults to None."""
    from nanobot.config.schema import Config

    config = Config()
    assert config.agents.defaults.timezone is None


def test_config_invalid_timezone_loads_gracefully() -> None:
    """Invalid timezone in config should NOT crash config loading — no strict validator."""
    from nanobot.config.schema import Config

    # This MUST succeed (no validator = no crash). The invalid tz is handled at usage time.
    config = Config.model_validate({
        "agents": {"defaults": {"timezone": "Invalid/Zone"}}
    })
    assert config.agents.defaults.timezone == "Invalid/Zone"
    # current_time_str gracefully falls back
    result = current_time_str(config.agents.defaults.timezone)
    assert "Invalid/Zone" not in result


# --- Deprecation fallback tests ---


def test_resolve_timezone_prefers_config(tmp_path: Path) -> None:
    """_resolve_timezone should prefer config.json timezone over USER.md."""
    from nanobot.cli.commands import _resolve_timezone
    from nanobot.config.schema import Config

    # USER.md has timezone but config also has one
    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: Europe/London\n", encoding="utf-8"
    )
    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path), "timezone": "Asia/Tokyo"}}
    })
    assert _resolve_timezone(config) == "Asia/Tokyo"


def test_resolve_timezone_fallback_to_user_md(tmp_path: Path) -> None:
    """_resolve_timezone should fallback to USER.md when config.timezone is None."""
    from nanobot.cli.commands import _resolve_timezone
    from nanobot.config.schema import Config

    (tmp_path / "USER.md").write_text(
        "# User Profile\n- **Timezone**: America/New_York\n", encoding="utf-8"
    )
    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path)}}
    })
    with patch("loguru.logger.warning") as mock_warn:
        result = _resolve_timezone(config)
        assert result == "America/New_York"
        mock_warn.assert_called_once()
        assert "deprecated" in str(mock_warn.call_args).lower()


def test_resolve_timezone_no_tz_anywhere(tmp_path: Path) -> None:
    """_resolve_timezone returns None when neither config nor USER.md has timezone."""
    from nanobot.cli.commands import _resolve_timezone
    from nanobot.config.schema import Config

    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path)}}
    })
    assert _resolve_timezone(config) is None


# --- Subagent timezone wiring test ---


def test_subagent_manager_passes_timezone(tmp_path: Path) -> None:
    """SubagentManager should pass timezone to _build_runtime_context."""
    from unittest.mock import MagicMock
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test"
    bus = MessageBus()

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        timezone="Europe/Berlin",
    )
    assert mgr.timezone == "Europe/Berlin"

    # _build_subagent_prompt should contain the timezone
    prompt = mgr._build_subagent_prompt()
    assert "(Europe/Berlin)" in prompt


# --- Heartbeat timezone wiring test ---


@pytest.mark.asyncio
async def test_heartbeat_uses_constructor_timezone(tmp_path: Path) -> None:
    """HeartbeatService should use timezone from constructor, not USER.md."""
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.providers.base import LLMProvider, LLMResponse

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
        timezone="America/New_York",
    )

    await service._decide("test heartbeat content")
    assert service._user_tz == "America/New_York"
    assert any("(America/New_York)" in str(m.get("content", "")) for m in provider.captured_messages)
