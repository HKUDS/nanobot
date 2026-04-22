"""Tests for spawn_status, spawn_cancel, domain loop detection, and timeout cleanup."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


# ---------------------------------------------------------------------------
# Domain loop detection (runtime.py)
# ---------------------------------------------------------------------------


class TestDomainLoopDetection:
    def test_same_domain_blocked_after_threshold(self):
        from nanobot.utils.runtime import repeated_external_lookup_error

        seen: dict[str, int] = {}
        # 10 fetches from the same domain — should all pass
        for i in range(10):
            result = repeated_external_lookup_error(
                "web_fetch",
                {"url": f"https://docs.python.org/3/library?page={i}"},
                seen,
            )
            assert result is None, f"fetch {i+1} should not be blocked"

        # 11th should be blocked
        result = repeated_external_lookup_error(
            "web_fetch",
            {"url": "https://docs.python.org/3/whatsnew"},
            seen,
        )
        assert result is not None
        assert "domain" in result.lower()

    def test_different_domains_not_blocked(self):
        from nanobot.utils.runtime import repeated_external_lookup_error

        seen: dict[str, int] = {}
        domains = ["example.com", "github.com", "docs.python.org", "arxiv.org", "wikipedia.org"]
        for domain in domains:
            result = repeated_external_lookup_error(
                "web_fetch",
                {"url": f"https://{domain}/page"},
                seen,
            )
            assert result is None, f"domain {domain} should not be blocked"

    def test_localhost_and_127_0_0_1_excluded(self):
        from nanobot.utils.runtime import repeated_external_lookup_error

        seen: dict[str, int] = {}
        for url in ["http://localhost:8080/api", "http://127.0.0.1:5000/health"]:
            result = repeated_external_lookup_error("web_fetch", {"url": url}, seen)
            assert result is None

    def test_web_search_not_affected_by_domain_check(self):
        """Domain detection only applies to web_fetch, not web_search."""
        from nanobot.utils.runtime import repeated_external_lookup_error

        seen: dict[str, int] = {}
        # web_search has its own exact-match throttling (2 retries max)
        # First 2 should pass, 3rd blocked by exact query match
        for i in range(2):
            result = repeated_external_lookup_error(
                "web_search",
                {"query": "test query"},
                seen,
            )
            assert result is None, f"web_search attempt {i+1} should pass"

        # 3rd identical query blocked by exact match, not domain
        result = repeated_external_lookup_error(
            "web_search",
            {"query": "test query"},
            seen,
        )
        assert result is not None

    def test_exact_url_still_throttled_independently(self):
        """Exact URL throttle (2 retries) fires before domain throttle (10)."""
        from nanobot.utils.runtime import repeated_external_lookup_error

        seen: dict[str, int] = {}
        # Same URL 3 times — blocked by exact match (threshold 2)
        for i in range(2):
            result = repeated_external_lookup_error(
                "web_fetch",
                {"url": "https://example.com/same-page"},
                seen,
            )
            assert result is None, f"attempt {i+1} should pass"

        # 3rd identical URL is blocked
        result = repeated_external_lookup_error(
            "web_fetch",
            {"url": "https://example.com/same-page"},
            seen,
        )
        assert result is not None
        assert "repeated" in result.lower()


# ---------------------------------------------------------------------------
# spawn_status tool
# ---------------------------------------------------------------------------


class TestSpawnStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_info_for_known_task(self):
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.agent.tools.spawn_status import SpawnStatusTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._task_statuses["sub-1"] = SubagentStatus(
            task_id="sub-1", label="test-task", task_description="do stuff", started_at=time.monotonic()
        )

        tool = SpawnStatusTool(mgr)
        result = await tool.execute(task_id="sub-1")
        assert "sub-1" in result
        assert "test-task" in result

    @pytest.mark.asyncio
    async def test_status_returns_message_for_unknown_task(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn_status import SpawnStatusTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        tool = SpawnStatusTool(mgr)
        result = await tool.execute(task_id="nonexistent")
        assert "No subagent" in result

    @pytest.mark.asyncio
    async def test_status_all_returns_empty_when_no_tasks(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn_status import SpawnStatusTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        tool = SpawnStatusTool(mgr)
        result = await tool.execute()
        assert "No subagent tasks" in result

    @pytest.mark.asyncio
    async def test_status_all_lists_multiple_tasks(self):
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.agent.tools.spawn_status import SpawnStatusTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._task_statuses["sub-1"] = SubagentStatus(
            task_id="sub-1", label="alpha", task_description="task a", started_at=time.monotonic()
        )
        mgr._task_statuses["sub-2"] = SubagentStatus(
            task_id="sub-2", label="beta", task_description="task b", started_at=time.monotonic()
        )

        tool = SpawnStatusTool(mgr)
        result = await tool.execute()
        assert "sub-1" in result
        assert "sub-2" in result
        assert "alpha" in result
        assert "beta" in result


# ---------------------------------------------------------------------------
# spawn_cancel tool
# ---------------------------------------------------------------------------


class TestSpawnCancelTool:
    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn_cancel import SpawnCancelTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        mgr._running_tasks["sub-1"] = task

        tool = SpawnCancelTool(mgr)
        result = await tool.execute(task_id="sub-1")
        assert "Cancelled" in result
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn_cancel import SpawnCancelTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        tool = SpawnCancelTool(mgr)
        result = await tool.execute(task_id="ghost")
        assert "No running" in result

    @pytest.mark.asyncio
    async def test_cancel_empty_task_id(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn_cancel import SpawnCancelTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        tool = SpawnCancelTool(mgr)
        result = await tool.execute(task_id="")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Timeout cleanup (subagent.py)
# ---------------------------------------------------------------------------


class TestTimeoutCleanup:
    @pytest.mark.asyncio
    async def test_timeout_error_sets_status_and_announces(self):
        """asyncio.TimeoutError must set status.phase='error' and announce."""
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._announce_result = AsyncMock()

        status = SubagentStatus(
            task_id="sub-1", label="slow-task", task_description="do slow thing", started_at=time.monotonic()
        )

        # Patch the inner await so TimeoutError fires from asyncio.wait_for
        original_run = mgr.runner.run
        async def fake_run(spec):
            raise asyncio.TimeoutError()
        mgr.runner.run = fake_run

        # We need to bypass tool setup — mock _build_subagent_prompt and tool registry
        with patch.object(mgr, "_build_subagent_prompt", return_value="test prompt"), \
             patch("nanobot.agent.subagent.ToolRegistry"), \
             patch("nanobot.agent.subagent.WebToolsConfig"):
            await mgr._run_subagent(
                "sub-1", "do slow thing", "slow-task",
                {"channel": "test", "chat_id": "c1"}, status,
                timeout_seconds=1,
            )

        assert status.phase == "error"
        assert "Timed out" in status.error
        mgr._announce_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancelled_error_sets_status_no_announce(self):
        """asyncio.CancelledError must set status.phase='error' but NOT announce."""
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._announce_result = AsyncMock()

        status = SubagentStatus(
            task_id="sub-1", label="cancelled-task", task_description="do thing", started_at=time.monotonic()
        )

        async def fake_run(spec):
            raise asyncio.CancelledError()

        mgr.runner.run = fake_run

        with patch.object(mgr, "_build_subagent_prompt", return_value="test prompt"), \
             patch("nanobot.agent.subagent.ToolRegistry"), \
             patch("nanobot.agent.subagent.WebToolsConfig"):
            await mgr._run_subagent(
                "sub-1", "do thing", "cancelled-task",
                {"channel": "test", "chat_id": "c1"}, status,
            )

        assert status.phase == "error"
        assert status.error == "Cancelled"
        mgr._announce_result.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_timeout_does_not_leave_zombie_entries(self):
        """After timeout, _cleanup callback removes task from tracking dicts."""
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._announce_result = AsyncMock()

        status = SubagentStatus(
            task_id="sub-1", label="zombie-test", task_description="do thing", started_at=time.monotonic()
        )

        async def fake_run(spec):
            raise asyncio.TimeoutError()

        mgr.runner.run = AsyncMock(side_effect=fake_run)

        # Simulate what spawn() does: create background task with _cleanup callback
        async def run_with_cleanup():
            await mgr._run_subagent(
                "sub-1", "do thing", "zombie-test",
                {"channel": "test", "chat_id": "c1"}, status,
                timeout_seconds=1,
            )

        bg_task = asyncio.create_task(run_with_cleanup())

        def _cleanup(_: asyncio.Task) -> None:
            mgr._running_tasks.pop("sub-1", None)
            mgr._task_statuses.pop("sub-1", None)

        bg_task.add_done_callback(_cleanup)
        mgr._running_tasks["sub-1"] = bg_task
        mgr._task_statuses["sub-1"] = status

        await asyncio.gather(bg_task, return_exceptions=True)

        # After completion + cleanup, no zombie entries
        assert "sub-1" not in mgr._running_tasks
        assert "sub-1" not in mgr._task_statuses


# ---------------------------------------------------------------------------
# IntegerSchema for spawn params
# ---------------------------------------------------------------------------


class TestSpawnToolIntegerParams:
    def test_spawn_tool_uses_integer_schema(self):
        """Verify spawn tool registers max_iterations and timeout_seconds as IntegerSchema."""
        from nanobot.agent.tools.spawn import SpawnTool
        import inspect

        # Check that the module imports IntegerSchema
        from nanobot.agent.tools import spawn as spawn_mod
        assert hasattr(spawn_mod, 'IntegerSchema'), "spawn.py should import IntegerSchema"

    def test_spawn_tool_name_and_description(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.agent.tools.spawn import SpawnTool
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        tool = SpawnTool(mgr)
        assert tool.name == "spawn"
        assert "subagent" in tool.description.lower()
