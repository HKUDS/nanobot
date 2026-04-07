"""Tests for unified_session feature.

Covers:
- AgentLoop._dispatch() rewrites session_key to "unified:default" when enabled
- Existing session_key_override is respected (not overwritten)
- Feature is off by default (no behavior change for existing users)
- Config schema serialises unified_session as camelCase "unifiedSession"
- onboard-generated config.json contains "unifiedSession" key
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loop(tmp_path: Path, unified_session: bool = False) -> AgentLoop:
    """Create a minimal AgentLoop for dispatch-level tests."""
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr, \
         patch("nanobot.agent.loop.Dream"):
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            unified_session=unified_session,
        )
    return loop


def _make_msg(channel: str = "telegram", chat_id: str = "111",
              session_key_override: str | None = None) -> InboundMessage:
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id="user1",
        content="hello",
        session_key_override=session_key_override,
    )


# ---------------------------------------------------------------------------
# TestUnifiedSessionDispatch — core behaviour
# ---------------------------------------------------------------------------

class TestUnifiedSessionDispatch:
    """AgentLoop._dispatch() session key rewriting logic."""

    @pytest.mark.asyncio
    async def test_unified_session_rewrites_key_to_unified_default(self, tmp_path: Path):
        """When unified_session=True, all messages use 'unified:default' as session key."""
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="111")
        await loop._dispatch(msg)

        assert captured == ["unified:default"]

    @pytest.mark.asyncio
    async def test_unified_session_different_channels_share_same_key(self, tmp_path: Path):
        """Messages from different channels all resolve to the same session key."""
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        await loop._dispatch(_make_msg(channel="telegram", chat_id="111"))
        await loop._dispatch(_make_msg(channel="discord", chat_id="222"))
        await loop._dispatch(_make_msg(channel="cli", chat_id="direct"))

        assert captured == ["unified:default", "unified:default", "unified:default"]

    @pytest.mark.asyncio
    async def test_unified_session_disabled_preserves_original_key(self, tmp_path: Path):
        """When unified_session=False (default), session key is channel:chat_id as usual."""
        loop = _make_loop(tmp_path, unified_session=False)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="999")
        await loop._dispatch(msg)

        assert captured == ["telegram:999"]

    @pytest.mark.asyncio
    async def test_unified_session_respects_existing_override(self, tmp_path: Path):
        """If session_key_override is already set (e.g. Telegram thread), it is NOT overwritten."""
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="111", session_key_override="telegram:thread:42")
        await loop._dispatch(msg)

        assert captured == ["telegram:thread:42"]

    def test_unified_session_default_is_false(self, tmp_path: Path):
        """unified_session defaults to False — no behavior change for existing users."""
        loop = _make_loop(tmp_path)
        assert loop._unified_session is False


# ---------------------------------------------------------------------------
# TestUnifiedSessionConfig — schema & serialisation
# ---------------------------------------------------------------------------

class TestUnifiedSessionConfig:
    """Config schema and onboard serialisation for unified_session."""

    def test_agent_defaults_unified_session_default_is_false(self):
        """AgentDefaults.unified_session defaults to False."""
        defaults = AgentDefaults()
        assert defaults.unified_session is False

    def test_agent_defaults_unified_session_can_be_enabled(self):
        """AgentDefaults.unified_session can be set to True."""
        defaults = AgentDefaults(unified_session=True)
        assert defaults.unified_session is True

    def test_config_serialises_unified_session_as_camel_case(self):
        """model_dump(by_alias=True) outputs 'unifiedSession' (camelCase) for JSON."""
        config = Config()
        data = config.model_dump(mode="json", by_alias=True)
        agents_defaults = data["agents"]["defaults"]
        assert "unifiedSession" in agents_defaults
        assert agents_defaults["unifiedSession"] is False

    def test_config_parses_unified_session_from_camel_case(self):
        """Config can be loaded from JSON with camelCase 'unifiedSession'."""
        raw = {"agents": {"defaults": {"unifiedSession": True}}}
        config = Config.model_validate(raw)
        assert config.agents.defaults.unified_session is True

    def test_config_parses_unified_session_from_snake_case(self):
        """Config also accepts snake_case 'unified_session' (populate_by_name=True)."""
        raw = {"agents": {"defaults": {"unified_session": True}}}
        config = Config.model_validate(raw)
        assert config.agents.defaults.unified_session is True

    def test_onboard_generated_config_contains_unified_session(self, tmp_path: Path):
        """save_config() writes 'unifiedSession' into config.json (simulates nanobot onboard)."""
        from nanobot.config.loader import save_config

        config = Config()
        config_path = tmp_path / "config.json"
        save_config(config, config_path)

        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)

        agents_defaults = data["agents"]["defaults"]
        assert "unifiedSession" in agents_defaults, (
            "onboard-generated config.json must contain 'unifiedSession' key"
        )
        assert agents_defaults["unifiedSession"] is False
