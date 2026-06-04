"""Tests for the heartbeat service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blackcat.heartbeat.service import HeartbeatService

# ── _decide (Phase 1) ───────────────────────────────────────────────


def test_heartbeat_file_path(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
    )
    assert svc.heartbeat_file == tmp_path / "HEARTBEAT.md"


def test_read_heartbeat_file_missing(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
    )
    content = svc._read_heartbeat_file()
    assert content is None


def test_read_heartbeat_file_exists(tmp_path):
    hb = tmp_path / "HEARTBEAT.md"
    hb.write_text("# Active Tasks\n- Check server status\n")
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
    )
    content = svc._read_heartbeat_file()
    assert "Check server status" in content


@pytest.mark.asyncio
async def test_decide_returns_skip_on_empty(tmp_path):
    """Phase 1: LLM returns skip action."""
    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = False
    mock_response.has_tool_calls = False
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )

    action, tasks = await svc._decide("# No tasks")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_decide_returns_run_on_active_tasks(tmp_path):
    """Phase 1: LLM returns run action with tasks."""
    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = True
    mock_response.has_tool_calls = True
    mock_response.tool_calls = [
        MagicMock(arguments={"action": "run", "tasks": "Check server status"})
    ]
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )

    action, tasks = await svc._decide("# Active Tasks\n- Check server")
    assert action == "run"
    assert tasks == "Check server status"


# ── _tick (Phase 2) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_skips_missing_file(tmp_path):
    """If HEARTBEAT.md is missing, _tick should not call on_execute."""
    called = False

    async def on_execute(tasks):
        nonlocal called
        called = True
        return "done"

    provider = MagicMock()
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=on_execute,
    )
    await svc._tick()
    assert called is False


@pytest.mark.asyncio
async def test_tick_skips_on_llm_skip(tmp_path):
    """If LLM decides skip, _tick should not call on_execute."""
    called = False

    async def on_execute(tasks):
        nonlocal called
        called = True
        return "done"

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = False
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    # Create file so _read_heartbeat_file returns content
    hb = tmp_path / "HEARTBEAT.md"
    hb.write_text("# Empty")

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=on_execute,
    )
    await svc._tick()
    assert called is False


@pytest.mark.asyncio
async def test_tick_calls_on_execute_on_run(tmp_path):
    """If LLM decides run, _tick should call on_execute."""
    received_tasks = None

    async def on_execute(tasks):
        nonlocal received_tasks
        received_tasks = tasks
        return "Completed: " + tasks

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = True
    mock_response.has_tool_calls = True
    mock_response.tool_calls = [
        MagicMock(arguments={"action": "run", "tasks": "Check server"})
    ]
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    hb = tmp_path / "HEARTBEAT.md"
    hb.write_text("# Active\n- Check server")

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=on_execute,
    )
    await svc._tick()
    assert received_tasks == "Check server"


@pytest.mark.asyncio
async def test_tick_calls_on_notify_when_evaluation_passes(tmp_path):
    """If on_execute returns and evaluation passes, on_notify should be called."""
    notify_received = None

    async def on_execute(tasks):
        return "Response content"

    async def on_notify(content):
        nonlocal notify_received
        notify_received = content

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = True
    mock_response.has_tool_calls = True
    mock_response.tool_calls = [
        MagicMock(arguments={"action": "run", "tasks": "Do task"})
    ]
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    # Mock evaluate_response to return True (should notify)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "blackcat.utils.evaluator.evaluate_response",
            AsyncMock(return_value=True),
        )

        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text("# Active\n- Do task")

        svc = HeartbeatService(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            on_execute=on_execute,
            on_notify=on_notify,
        )
        await svc._tick()
        assert notify_received == "Response content"


@pytest.mark.asyncio
async def test_tick_skips_notify_when_evaluation_fails(tmp_path):
    """If evaluation fails, on_notify should not be called."""
    notify_called = False

    async def on_execute(tasks):
        return "Response content"

    async def on_notify(content):
        nonlocal notify_called
        notify_called = True

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = True
    mock_response.has_tool_calls = True
    mock_response.tool_calls = [
        MagicMock(arguments={"action": "run", "tasks": "Do task"})
    ]
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "blackcat.utils.evaluator.evaluate_response",
            AsyncMock(return_value=False),
        )

        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text("# Active\n- Do task")

        svc = HeartbeatService(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            on_execute=on_execute,
            on_notify=on_notify,
        )
        await svc._tick()
        assert notify_called is False


# ── start/stop ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_disabled(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
        enabled=False,
    )
    await svc.start()
    assert svc._task is None


@pytest.mark.asyncio
async def test_start_already_running(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
        enabled=True,
        interval_s=1,
    )
    await svc.start()
    assert svc._task is not None

    # Second start should set _task to None and return early
    # (the warning is logged but we can't easily capture loguru logs)
    initial_task = svc._task
    await svc.start()
    # Second start should not replace the task
    assert svc._task is initial_task

    svc.stop()


def test_stop(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
    )
    svc._running = True
    # Don't create a real task outside of event loop - just test the flag
    svc._task = None
    svc.stop()
    assert svc._running is False
    assert svc._task is None


# ── trigger_now ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_now_no_file(tmp_path):
    svc = HeartbeatService(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
    )
    result = await svc.trigger_now()
    assert result is None


@pytest.mark.asyncio
async def test_trigger_now_skips_on_llm_skip(tmp_path):
    """trigger_now respects LLM skip decision."""
    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = False
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    hb = tmp_path / "HEARTBEAT.md"
    hb.write_text("# Empty")

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )
    result = await svc.trigger_now()
    assert result is None


@pytest.mark.asyncio
async def test_trigger_now_executes_on_run(tmp_path):
    """trigger_now executes tasks when LLM decides run."""
    received_tasks = None

    async def on_execute(tasks):
        nonlocal received_tasks
        received_tasks = tasks
        return "Done: " + tasks

    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.should_execute_tools = True
    mock_response.has_tool_calls = True
    mock_response.tool_calls = [
        MagicMock(arguments={"action": "run", "tasks": "Manual task"})
    ]
    provider.chat_with_retry = AsyncMock(return_value=mock_response)

    hb = tmp_path / "HEARTBEAT.md"
    hb.write_text("# Active\n- Manual task")

    svc = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=on_execute,
    )
    result = await svc.trigger_now()
    assert received_tasks == "Manual task"
    assert result == "Done: Manual task"
