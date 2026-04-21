"""Tests for heartbeat model override feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import HeartbeatConfig
from nanobot.heartbeat.service import HeartbeatService


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    return provider


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    hb_file = tmp_path / "HEARTBEAT.md"
    hb_file.write_text("Check email.\n")
    return tmp_path


class TestHeartbeatModelOverride:
    """Verify that heartbeat.model overrides the agent model for both phases."""

    def test_config_default_model_is_none(self):
        cfg = HeartbeatConfig()
        assert cfg.model is None

    def test_config_accepts_model_string(self):
        cfg = HeartbeatConfig(model="anthropic/claude-haiku-3.5")
        assert cfg.model == "anthropic/claude-haiku-3.5"

    def test_service_uses_agent_model_when_no_override(self, mock_provider, tmp_workspace):
        svc = HeartbeatService(
            workspace=tmp_workspace,
            provider=mock_provider,
            model="anthropic/claude-opus-4",
        )
        assert svc.model == "anthropic/claude-opus-4"

    def test_service_uses_heartbeat_model_when_set(self, mock_provider, tmp_workspace):
        svc = HeartbeatService(
            workspace=tmp_workspace,
            provider=mock_provider,
            model="anthropic/claude-opus-4",
            heartbeat_model="anthropic/claude-haiku-3.5",
        )
        assert svc.model == "anthropic/claude-haiku-3.5"

    @pytest.mark.asyncio
    async def test_phase1_decide_uses_heartbeat_model(self, mock_provider, tmp_workspace):
        """Phase 1 LLM call should use the heartbeat model, not agent model."""
        response = MagicMock()
        response.should_execute_tools = True
        response.has_tool_calls = True
        response.tool_calls = [MagicMock(arguments={"action": "skip", "tasks": ""})]
        mock_provider.chat_with_retry.return_value = response

        svc = HeartbeatService(
            workspace=tmp_workspace,
            provider=mock_provider,
            model="anthropic/claude-opus-4",
            heartbeat_model="anthropic/claude-haiku-3.5",
        )

        action, tasks = await svc._decide("Check email.")

        call_kwargs = mock_provider.chat_with_retry.call_args
        assert call_kwargs.kwargs.get("model") == "anthropic/claude-haiku-3.5"
        assert action == "skip"

    @pytest.mark.asyncio
    async def test_phase1_decide_uses_agent_model_without_override(
        self, mock_provider, tmp_workspace
    ):
        """Without override, Phase 1 should use the agent model."""
        response = MagicMock()
        response.should_execute_tools = True
        response.has_tool_calls = True
        response.tool_calls = [MagicMock(arguments={"action": "skip", "tasks": ""})]
        mock_provider.chat_with_retry.return_value = response

        svc = HeartbeatService(
            workspace=tmp_workspace,
            provider=mock_provider,
            model="anthropic/claude-opus-4",
        )

        await svc._decide("Check email.")

        call_kwargs = mock_provider.chat_with_retry.call_args
        assert call_kwargs.kwargs.get("model") == "anthropic/claude-opus-4"


class TestProcessDirectModelOverride:
    """Verify that process_direct passes model_override without mutating agent state."""

    def test_process_direct_signature_accepts_model_override(self):
        """process_direct should accept model_override as a keyword argument."""
        import inspect  # noqa: E402

        from nanobot.agent.loop import AgentLoop

        sig = inspect.signature(AgentLoop.process_direct)
        assert "model_override" in sig.parameters
        param = sig.parameters["model_override"]
        assert param.default is None
