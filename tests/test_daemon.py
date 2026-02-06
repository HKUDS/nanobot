"""Tests for daemon three-tier logic and DaemonConfig."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.heartbeat.service import HeartbeatService, _is_heartbeat_empty


class TestIsHeartbeatEmpty:
    """Tests for the _is_heartbeat_empty helper."""

    def test_none_is_empty(self) -> None:
        assert _is_heartbeat_empty(None) is True

    def test_empty_string_is_empty(self) -> None:
        assert _is_heartbeat_empty("") is True

    def test_only_headers_is_empty(self) -> None:
        assert _is_heartbeat_empty("# Tasks\n## Subtasks") is True

    def test_only_empty_checkboxes_is_empty(self) -> None:
        assert _is_heartbeat_empty("- [ ]\n* [ ]") is True

    def test_completed_checkboxes_is_empty(self) -> None:
        assert _is_heartbeat_empty("- [x]\n* [x]") is True

    def test_html_comments_is_empty(self) -> None:
        assert _is_heartbeat_empty("<!-- comment -->") is True

    def test_with_content_is_not_empty(self) -> None:
        assert _is_heartbeat_empty("# Tasks\n- Do something") is False

    def test_whitespace_only_is_empty(self) -> None:
        assert _is_heartbeat_empty("   \n  \n") is True

    def test_mixed_empty_with_content(self) -> None:
        assert _is_heartbeat_empty("# Header\n\n- [x]\n- Build it") is False


class TestLegacyHeartbeat:
    """Tests for legacy (non-daemon) heartbeat path."""

    @pytest.mark.asyncio
    async def test_legacy_mode_when_no_triage(self, tmp_path: Path) -> None:
        """Without triage_provider, uses legacy heartbeat path."""
        on_hb = AsyncMock(return_value="HEARTBEAT_OK")
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
        )
        (tmp_path / "HEARTBEAT.md").write_text("- Do task", encoding="utf-8")

        await svc._tick()
        on_hb.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_skips_empty_file(self, tmp_path: Path) -> None:
        """Legacy path does nothing when strategy file is empty."""
        on_hb = AsyncMock()
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
        )
        (tmp_path / "HEARTBEAT.md").write_text("# Tasks\n", encoding="utf-8")

        await svc._tick()
        on_hb.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_skips_missing_file(self, tmp_path: Path) -> None:
        """Legacy path does nothing when strategy file is absent."""
        on_hb = AsyncMock()
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
        )

        await svc._tick()
        on_hb.assert_not_called()


class TestDaemonTierZero:
    """Tests for Tier 0: context gathering."""

    @pytest.mark.asyncio
    async def test_gather_context_reads_strategy(self, tmp_path: Path) -> None:
        """Tier 0 reads strategy file content."""
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
        )
        (tmp_path / "HEARTBEAT.md").write_text(
            "- Build feature",
            encoding="utf-8",
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"## main\n", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            ctx = await svc._gather_context()

        assert ctx["strategy_content"] is not None
        assert "Build feature" in ctx["strategy_content"]
        assert ctx["has_signals"] is True

    @pytest.mark.asyncio
    async def test_gather_context_no_strategy_file(self, tmp_path: Path) -> None:
        """Tier 0 returns has_signals=False when no file exists."""
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            ctx = await svc._gather_context()

        assert ctx["strategy_content"] is None
        assert ctx["has_signals"] is False

    @pytest.mark.asyncio
    async def test_gather_context_git_status(self, tmp_path: Path) -> None:
        """Tier 0 captures git status output."""
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
        )
        (tmp_path / "HEARTBEAT.md").write_text("- task", encoding="utf-8")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(
                return_value=(b"## main\n M file.py", b""),
            )
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            ctx = await svc._gather_context()

        assert ctx["git_status"] is not None
        assert "file.py" in ctx["git_status"]


class TestDaemonTierOne:
    """Tests for Tier 1: triage via cheap LLM call."""

    @pytest.mark.asyncio
    async def test_triage_returns_act(self, tmp_path: Path) -> None:
        """Tier 1 parses triage response correctly."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "act": True,
                "reason": "Task found",
                "priority": "high",
            }
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )

        ctx = {
            "strategy_content": "- Build feature",
            "git_status": "",
            "tmux_sessions": "",
        }
        result = await svc._triage(ctx)
        assert result["act"] is True
        assert result["reason"] == "Task found"
        assert result["priority"] == "high"

    @pytest.mark.asyncio
    async def test_triage_returns_no_act(self, tmp_path: Path) -> None:
        """Tier 1 parses act=false correctly."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "act": False,
                "reason": "All done",
                "priority": "low",
            }
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )

        ctx = {
            "strategy_content": "- [x] Done task",
            "git_status": "",
            "tmux_sessions": "",
        }
        result = await svc._triage(ctx)
        assert result["act"] is False

    @pytest.mark.asyncio
    async def test_triage_handles_parse_error(self, tmp_path: Path) -> None:
        """Tier 1 gracefully handles non-JSON response."""
        mock_response = MagicMock()
        mock_response.content = "not json at all"
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )

        ctx = {
            "strategy_content": "- Build feature",
            "git_status": "",
            "tmux_sessions": "",
        }
        result = await svc._triage(ctx)
        assert result["act"] is False

    @pytest.mark.asyncio
    async def test_triage_strips_code_fences(self, tmp_path: Path) -> None:
        """Tier 1 handles markdown code-fenced JSON."""
        mock_response = MagicMock()
        mock_response.content = (
            '```json\n{"act": true, "reason": "Found", "priority": "medium"}\n```'
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )

        ctx = {
            "strategy_content": "- Build feature",
            "git_status": "",
            "tmux_sessions": "",
        }
        result = await svc._triage(ctx)
        assert result["act"] is True
        assert result["reason"] == "Found"

    @pytest.mark.asyncio
    async def test_triage_calls_provider_with_correct_params(
        self,
        tmp_path: Path,
    ) -> None:
        """Tier 1 passes correct model and temperature to provider."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "act": False,
                "reason": "Nothing",
                "priority": "low",
            }
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="gemini/flash-lite",
        )

        ctx = {
            "strategy_content": "- task",
            "git_status": "clean",
            "tmux_sessions": "",
        }
        await svc._triage(ctx)

        mock_provider.chat.assert_called_once()
        call_kwargs = mock_provider.chat.call_args
        assert call_kwargs.kwargs["model"] == "gemini/flash-lite"
        assert call_kwargs.kwargs["temperature"] == 0.2
        assert call_kwargs.kwargs["max_tokens"] == 256


class TestDaemonTierTwo:
    """Tests for Tier 2: execution via main agent."""

    @pytest.mark.asyncio
    async def test_execute_calls_on_heartbeat(self, tmp_path: Path) -> None:
        """Tier 2 calls on_heartbeat with rich prompt."""
        on_hb = AsyncMock(return_value="Done")
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
            cooldown_after_action=0,
        )

        ctx = {
            "strategy_content": "- Build feature",
            "git_status": "clean",
            "tmux_sessions": "",
        }
        triage = {"act": True, "reason": "Task found", "priority": "high"}

        await svc._execute_daemon_action(ctx, triage)
        on_hb.assert_called_once()
        prompt = on_hb.call_args[0][0]
        assert "Build feature" in prompt
        assert "high" in prompt.lower()

    @pytest.mark.asyncio
    async def test_execute_updates_last_action_time(
        self,
        tmp_path: Path,
    ) -> None:
        """Tier 2 records the action timestamp."""
        on_hb = AsyncMock(return_value="Done")
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
            cooldown_after_action=0,
        )

        before = time.time()
        ctx = {
            "strategy_content": "- task",
            "git_status": "",
            "tmux_sessions": "",
        }
        triage = {"act": True, "reason": "go", "priority": "low"}
        await svc._execute_daemon_action(ctx, triage)

        assert svc._last_action_time >= before

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_execution(
        self,
        tmp_path: Path,
    ) -> None:
        """Cooldown prevents action within cooldown window."""
        on_hb = AsyncMock(return_value="Done")
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
            cooldown_after_action=600,
        )
        svc._last_action_time = time.time()

        ctx = {
            "strategy_content": "- Build feature",
            "git_status": "",
            "tmux_sessions": "",
        }
        triage = {"act": True, "reason": "Task found", "priority": "high"}

        await svc._execute_daemon_action(ctx, triage)
        on_hb.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_allows_after_expiry(self, tmp_path: Path) -> None:
        """Action proceeds when cooldown has expired."""
        on_hb = AsyncMock(return_value="Done")
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test-model",
            cooldown_after_action=10,
        )
        svc._last_action_time = time.time() - 20  # 20s ago, cooldown is 10s

        ctx = {
            "strategy_content": "- task",
            "git_status": "",
            "tmux_sessions": "",
        }
        triage = {"act": True, "reason": "go", "priority": "low"}
        await svc._execute_daemon_action(ctx, triage)
        on_hb.assert_called_once()


class TestDaemonTick:
    """Tests for the full daemon tick orchestrator."""

    @pytest.mark.asyncio
    async def test_full_daemon_tick_skips_no_signals(
        self,
        tmp_path: Path,
    ) -> None:
        """Daemon tick skips when no signals."""
        mock_provider = AsyncMock()
        on_hb = AsyncMock()
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await svc._daemon_tick()

        mock_provider.chat.assert_not_called()
        on_hb.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_daemon_tick_triage_says_no(
        self,
        tmp_path: Path,
    ) -> None:
        """Daemon tick stops after triage says act=false."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "act": False,
                "reason": "Nothing to do",
                "priority": "low",
            }
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)
        on_hb = AsyncMock()

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
        )
        (tmp_path / "HEARTBEAT.md").write_text(
            "- Build feature",
            encoding="utf-8",
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await svc._daemon_tick()

        mock_provider.chat.assert_called_once()
        on_hb.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_daemon_tick_executes(self, tmp_path: Path) -> None:
        """Full three-tier flow when signals + act=true."""
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "act": True,
                "reason": "Task found",
                "priority": "medium",
            }
        )
        mock_provider = AsyncMock()
        mock_provider.chat = AsyncMock(return_value=mock_response)
        on_hb = AsyncMock(return_value="Done")

        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=on_hb,
            interval_s=60,
            enabled=True,
            triage_provider=mock_provider,
            triage_model="test-model",
            cooldown_after_action=0,
        )
        (tmp_path / "HEARTBEAT.md").write_text(
            "- Build feature",
            encoding="utf-8",
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await svc._daemon_tick()

        mock_provider.chat.assert_called_once()
        on_hb.assert_called_once()


class TestDaemonModeDetection:
    """Tests for daemon vs legacy mode detection."""

    def test_daemon_mode_when_triage_provider_set(self, tmp_path: Path) -> None:
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test",
        )
        assert svc._daemon_mode is True

    def test_legacy_mode_when_no_triage_provider(self, tmp_path: Path) -> None:
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
        )
        assert svc._daemon_mode is False

    @pytest.mark.asyncio
    async def test_tick_dispatches_to_daemon(self, tmp_path: Path) -> None:
        """_tick delegates to _daemon_tick in daemon mode."""
        svc = HeartbeatService(
            workspace=tmp_path,
            on_heartbeat=AsyncMock(),
            interval_s=60,
            enabled=True,
            triage_provider=MagicMock(),
            triage_model="test",
        )
        with patch.object(svc, "_daemon_tick", new_callable=AsyncMock) as mock_dt:
            await svc._tick()
            mock_dt.assert_called_once()


class TestDaemonConfig:
    """Tests for DaemonConfig schema."""

    def test_daemon_config_defaults(self) -> None:
        from nanobot.config.schema import DaemonConfig

        cfg = DaemonConfig()
        assert cfg.enabled is True
        assert cfg.interval == 300
        assert cfg.triage_model is None
        assert cfg.triage_provider is None
        assert cfg.execution_model is None
        assert cfg.execution_provider is None
        assert cfg.strategy_file == "HEARTBEAT.md"
        assert cfg.max_iterations == 25
        assert cfg.cooldown_after_action == 600

    def test_daemon_config_from_json(self) -> None:
        from nanobot.config.schema import DaemonConfig

        cfg = DaemonConfig(
            **{
                "triageModel": "google/gemini-3-flash-lite",
                "triageProvider": "openrouter",
                "interval": 120,
                "cooldownAfterAction": 300,
            }
        )
        assert cfg.triage_model == "google/gemini-3-flash-lite"
        assert cfg.triage_provider == "openrouter"
        assert cfg.interval == 120
        assert cfg.cooldown_after_action == 300

    def test_daemon_config_custom_strategy_file(self) -> None:
        from nanobot.config.schema import DaemonConfig

        cfg = DaemonConfig(**{"strategyFile": "TODO.md"})
        assert cfg.strategy_file == "TODO.md"

    def test_agent_defaults_has_daemon(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults()
        assert hasattr(defaults, "daemon")
        assert defaults.daemon.enabled is True
        assert defaults.daemon.interval == 300
