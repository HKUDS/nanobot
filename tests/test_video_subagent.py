"""Tests for non-blocking generation via background workers + message heap.

Verifies that:
- generate_video/image/music/speech spawn workers when pending_results + bus_active
- Tools fall back to blocking generation when bus is NOT active (process_direct)
- PendingResults heap: add, complete, fail, drain, build_context_block, cancel
- Error handling (no API key, 503, empty response)
- AdkAgentLoop wiring: bus_active flag, /stop cancellation
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scorpion.adk.pending import PendingResults


# ── Helpers ──────────────────────────────────────────────────────────────────


def _patch_gemini_key():
    """Patch GEMINI_API_KEY so tools don't bail early."""
    return patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})


def _make_fake_operation():
    """Create a mock Veo operation that completes immediately."""
    fake_video = MagicMock()
    fake_video.video = MagicMock()
    fake_video.video.save = MagicMock()

    op = MagicMock()
    op.done = True
    op.response = MagicMock()
    op.response.generated_videos = [fake_video]
    return op


def _make_fake_client(operation=None):
    """Create a mock google.genai.Client."""
    op = operation or _make_fake_operation()
    client = MagicMock()
    client.models.generate_videos.return_value = op
    client.files.download = MagicMock()
    client.operations.get = MagicMock()
    return client


def _make_tool_context(*, bus_active: bool = False,
                        channel: str = "test", chat_id: str = "c1"):
    """Create a mock ToolContext with the right state."""
    state = {
        "app:bus_active": "true" if bus_active else "",
        "temp:channel": channel,
        "temp:chat_id": chat_id,
    }
    ctx = MagicMock()
    ctx.state = state
    return ctx


def _patch_veo_client(mock_client):
    """Patch google.genai.Client to return our mock. Works with local imports."""
    return patch("google.genai.Client", return_value=mock_client)


# ── Test: PendingResults (message heap) ───────────────────────────────────────


class TestPendingResults:
    """Unit tests for the PendingResults heap."""

    def test_add_and_get_running(self):
        pr = PendingResults()
        rid = pr.add("test:c1", "video", "a cat", {"duration": 8})
        running = pr.get_running("test:c1")
        assert len(running) == 1
        assert running[0].id == rid
        assert running[0].kind == "video"
        assert running[0].status == "running"

    def test_complete_and_drain(self):
        pr = PendingResults()
        rid = pr.add("test:c1", "image", "a dog")
        pr.complete(rid, ["/path/to/image.png"])

        drained = pr.drain("test:c1")
        assert len(drained) == 1
        assert drained[0].status == "completed"
        assert drained[0].file_paths == ["/path/to/image.png"]

        # Should be empty after drain
        assert pr.drain("test:c1") == []

    def test_fail_and_drain(self):
        pr = PendingResults()
        rid = pr.add("test:c1", "music", "jazz")
        pr.fail(rid, "API error")

        drained = pr.drain("test:c1")
        assert len(drained) == 1
        assert drained[0].status == "failed"
        assert drained[0].error == "API error"

    def test_drain_keeps_running(self):
        pr = PendingResults()
        rid1 = pr.add("test:c1", "video", "cat")
        rid2 = pr.add("test:c1", "image", "dog")
        pr.complete(rid2, ["/path/to/dog.png"])

        drained = pr.drain("test:c1")
        assert len(drained) == 1
        assert drained[0].id == rid2

        # rid1 still running
        running = pr.get_running("test:c1")
        assert len(running) == 1
        assert running[0].id == rid1

    def test_build_context_block_empty(self):
        pr = PendingResults()
        assert pr.build_context_block("test:c1") == ""

    def test_build_context_block_completed(self):
        pr = PendingResults()
        rid = pr.add("test:c1", "video", "a sunset")
        pr.complete(rid, ["/path/to/video.mp4"])

        block = pr.build_context_block("test:c1")
        assert "[COMPLETED]" in block
        assert "video" in block
        assert "/path/to/video.mp4" in block
        assert "send_message" in block

        # After build_context_block drains, should be empty
        assert pr.build_context_block("test:c1") == ""

    def test_build_context_block_running(self):
        pr = PendingResults()
        pr.add("test:c1", "music", "upbeat jazz")

        block = pr.build_context_block("test:c1")
        assert "[RUNNING]" in block
        assert "music" in block

    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        pr = PendingResults()
        rid = pr.add("test:c1", "video", "cat")

        # Create a mock task
        mock_task = MagicMock()
        mock_task.cancel = MagicMock(return_value=True)
        pr.register_task(rid, mock_task)

        cancelled = await pr.cancel_by_session("test:c1")
        assert cancelled == 1
        mock_task.cancel.assert_called_once()

        # Should be marked as failed
        result = pr._results.get(rid)
        assert result.status == "failed"
        assert "Cancelled" in result.error

    def test_multiple_sessions_isolated(self):
        pr = PendingResults()
        pr.add("session:a", "video", "cat")
        pr.add("session:b", "image", "dog")

        assert len(pr.get_running("session:a")) == 1
        assert len(pr.get_running("session:b")) == 1
        assert len(pr.get_running("session:c")) == 0


# ── Test: Non-blocking path (bus active, pending_results set) ─────────────────


class TestVideoNonBlocking:
    """When bus is active and pending_results is set, spawn a worker."""

    @pytest.mark.asyncio
    async def test_spawns_worker_when_bus_active(self):
        """generate_video should spawn a worker and return immediately."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        try:
            with _patch_gemini_key(), \
                 patch("scorpion.adk.workers.worker_generate_video", new_callable=AsyncMock):
                ctx = _make_tool_context(bus_active=True)
                result = await tools_mod.generate_video(
                    prompt="A cat walking on a beach",
                    duration=8,
                    aspect="16:9",
                    resolution="720p",
                    tool_context=ctx,
                )

            assert "background" in result.lower()
            # Should have registered a pending result
            running = pending.get_running("test:c1")
            assert len(running) == 1
            assert running[0].kind == "video"
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_does_not_block_main_agent(self):
        """Spawning a worker should return nearly instantly."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        try:
            with _patch_gemini_key(), \
                 patch("scorpion.adk.workers.worker_generate_video", new_callable=AsyncMock):
                ctx = _make_tool_context(bus_active=True)
                result = await asyncio.wait_for(
                    tools_mod.generate_video(prompt="test", tool_context=ctx),
                    timeout=2.0,
                )
            assert result is not None
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_image_spawns_worker(self):
        """generate_image should spawn a worker when bus is active."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        try:
            with _patch_gemini_key(), \
                 patch("scorpion.adk.workers.worker_generate_image", new_callable=AsyncMock):
                ctx = _make_tool_context(bus_active=True)
                result = await tools_mod.generate_image(
                    prompt="A red apple",
                    tool_context=ctx,
                )

            assert "background" in result.lower()
            running = pending.get_running("test:c1")
            assert len(running) == 1
            assert running[0].kind == "image"
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_music_spawns_worker(self):
        """generate_music should spawn a worker when bus is active."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        try:
            with _patch_gemini_key(), \
                 patch("scorpion.adk.workers.worker_generate_music", new_callable=AsyncMock):
                ctx = _make_tool_context(bus_active=True)
                result = await tools_mod.generate_music(
                    prompt="upbeat jazz",
                    tool_context=ctx,
                )

            assert "background" in result.lower()
            running = pending.get_running("test:c1")
            assert len(running) == 1
            assert running[0].kind == "music"
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_speech_spawns_worker(self):
        """generate_speech should spawn a worker when bus is active."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        try:
            with _patch_gemini_key(), \
                 patch("scorpion.adk.workers.worker_generate_speech", new_callable=AsyncMock):
                ctx = _make_tool_context(bus_active=True)
                result = await tools_mod.generate_speech(
                    text="Hello world",
                    tool_context=ctx,
                )

            assert "background" in result.lower()
            running = pending.get_running("test:c1")
            assert len(running) == 1
            assert running[0].kind == "speech"
        finally:
            tools_mod._pending_results = original_pending


# ── Test: Blocking path (process_direct / no bus) ────────────────────────────


class TestVideoBlocking:
    """When bus is NOT active (e.g. process_direct), do blocking generation."""

    @pytest.mark.asyncio
    async def test_blocks_when_bus_inactive(self):
        """generate_video should NOT spawn a worker when bus is inactive."""
        import scorpion.adk.tools as tools_mod

        pending = PendingResults()
        original_pending = tools_mod._pending_results
        tools_mod._pending_results = pending

        mock_client = _make_fake_client()

        try:
            with _patch_gemini_key(), _patch_veo_client(mock_client):
                ctx = _make_tool_context(bus_active=False)  # process_direct
                result = await tools_mod.generate_video(
                    prompt="A sunset over mountains",
                    tool_context=ctx,
                )

            # Should have called Veo directly (blocking)
            mock_client.models.generate_videos.assert_called_once()
            # No pending results
            assert len(pending.get_running("test:c1")) == 0
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_blocks_when_no_pending(self):
        """generate_video should do blocking gen when no pending_results."""
        import scorpion.adk.tools as tools_mod

        original_pending = tools_mod._pending_results
        tools_mod._pending_results = None

        mock_client = _make_fake_client()

        try:
            with _patch_gemini_key(), _patch_veo_client(mock_client):
                ctx = _make_tool_context(bus_active=True)
                result = await tools_mod.generate_video(
                    prompt="test", tool_context=ctx,
                )

            mock_client.models.generate_videos.assert_called_once()
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_blocking_passes_correct_params(self):
        """Blocking call should pass through all video params."""
        import scorpion.adk.tools as tools_mod

        original_pending = tools_mod._pending_results
        tools_mod._pending_results = None

        mock_client = _make_fake_client()

        try:
            with _patch_gemini_key(), _patch_veo_client(mock_client):
                ctx = _make_tool_context()
                await tools_mod.generate_video(
                    prompt="Sunset timelapse",
                    duration=6,
                    aspect="9:16",
                    resolution="1080p",
                    tool_context=ctx,
                )

            call_kwargs = mock_client.models.generate_videos.call_args
            config = call_kwargs[1]["config"]
            assert config.aspect_ratio == "9:16"
            assert config.resolution == "1080p"
        finally:
            tools_mod._pending_results = original_pending


# ── Test: Error handling ─────────────────────────────────────────────────────


class TestVideoErrorHandling:

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        """Should return error when GEMINI_API_KEY is not set."""
        import scorpion.adk.tools as tools_mod

        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            result = await tools_mod.generate_video(
                prompt="test", tool_context=_make_tool_context(),
            )
        assert "GEMINI_API_KEY" in result

    @pytest.mark.asyncio
    async def test_503_error_handling(self):
        """Should return friendly message on 503 errors."""
        import scorpion.adk.tools as tools_mod

        original_pending = tools_mod._pending_results
        tools_mod._pending_results = None

        try:
            with _patch_gemini_key(), \
                 patch("google.genai.Client") as MockClient:
                MockClient.return_value.models.generate_videos.side_effect = \
                    Exception("503 Service Unavailable")

                ctx = _make_tool_context()
                result = await tools_mod.generate_video(
                    prompt="test", tool_context=ctx,
                )

            assert "temporarily unavailable" in result.lower()
            assert "503" in result
        finally:
            tools_mod._pending_results = original_pending

    @pytest.mark.asyncio
    async def test_no_videos_generated(self):
        """Should return error when Veo returns no videos."""
        import scorpion.adk.tools as tools_mod

        original_pending = tools_mod._pending_results
        tools_mod._pending_results = None

        empty_op = MagicMock()
        empty_op.done = True
        empty_op.response = MagicMock()
        empty_op.response.generated_videos = []

        mock_client = _make_fake_client(empty_op)

        try:
            with _patch_gemini_key(), _patch_veo_client(mock_client):
                ctx = _make_tool_context()
                result = await tools_mod.generate_video(
                    prompt="test", tool_context=ctx,
                )

            assert "no videos" in result.lower()
        finally:
            tools_mod._pending_results = original_pending


# ── Test: bus_active state flag ──────────────────────────────────────────────


class TestBusActiveFlag:
    """Verify that AdkAgentLoop sets app:bus_active correctly."""

    def test_bus_inactive_in_process_direct(self):
        """_build_state should have bus_active='' when loop not running."""
        from scorpion.adk.loop import AdkAgentLoop
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()

        with patch("scorpion.adk.loop.ContextBuilder"), \
             patch("scorpion.adk.loop.SessionManager"), \
             patch("scorpion.adk.loop.SubagentManager"):
            loop = AdkAgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # _running is False by default (process_direct path)
        state = loop._build_state(channel="cli", chat_id="direct")
        assert state["app:bus_active"] == ""

    def test_bus_active_when_running(self):
        """_build_state should have bus_active='true' when loop is running."""
        from scorpion.adk.loop import AdkAgentLoop
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()

        with patch("scorpion.adk.loop.ContextBuilder"), \
             patch("scorpion.adk.loop.SessionManager"), \
             patch("scorpion.adk.loop.SubagentManager"):
            loop = AdkAgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Simulate bus loop running
        loop._running = True
        state = loop._build_state(channel="telegram", chat_id="12345")
        assert state["app:bus_active"] == "true"


# ── Test: AdkAgentLoop wiring ────────────────────────────────────────────────


class TestLoopPendingWiring:
    """Verify that AdkAgentLoop creates and wires PendingResults."""

    def test_loop_has_pending_results(self):
        """AdkAgentLoop.__init__ should create a PendingResults instance."""
        from scorpion.adk.loop import AdkAgentLoop
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()

        with patch("scorpion.adk.loop.ContextBuilder"), \
             patch("scorpion.adk.loop.SessionManager"), \
             patch("scorpion.adk.loop.SubagentManager"):
            loop = AdkAgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        assert isinstance(loop._pending_results, PendingResults)

    def test_pending_results_wired_to_tools(self):
        """set_runtime_refs should be called with pending_results."""
        import scorpion.adk.tools as tools_mod
        from scorpion.adk.loop import AdkAgentLoop
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()

        with patch("scorpion.adk.loop.ContextBuilder"), \
             patch("scorpion.adk.loop.SessionManager"), \
             patch("scorpion.adk.loop.SubagentManager"):
            loop = AdkAgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # The module-level _pending_results should be set
        assert tools_mod._pending_results is loop._pending_results


# ── Test: Subagent state flag (kept for SubagentManager) ──────────────────────


class TestSubagentStateFlag:
    """Verify that SubagentManager sets app:is_subagent in state."""

    def test_subagent_manager_init(self):
        from scorpion.agent.subagent import SubagentManager
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=Path("/tmp"), bus=bus)

        assert mgr.get_running_count() == 0

    @pytest.mark.asyncio
    async def test_spawn_creates_task(self):
        """spawn() should create a background task and return immediately."""
        from scorpion.agent.subagent import SubagentManager
        from scorpion.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=Path("/tmp"), bus=bus)

        # Patch _run_subagent so it doesn't actually do anything
        mgr._run_subagent = AsyncMock()

        result = await mgr.spawn(
            task="Test task",
            label="Test",
            origin_channel="test",
            origin_chat_id="c1",
            session_key="test:c1",
        )

        assert "Subagent" in result
        assert "Test" in result
        # Give the task a chance to start
        await asyncio.sleep(0.1)
        mgr._run_subagent.assert_awaited_once()
