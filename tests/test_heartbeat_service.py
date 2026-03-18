"""Tests for heartbeat service (tool-call-based decision phase)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.heartbeat.service import HeartbeatService


def _make_service(tmp_path, **overrides):
    """Create a HeartbeatService with sane test defaults."""
    provider = overrides.pop("provider", MagicMock())
    model = overrides.pop("model", "test-model")
    defaults = dict(
        workspace=tmp_path,
        provider=provider,
        model=model,
        interval_s=9999,
        enabled=True,
    )
    defaults.update(overrides)
    return HeartbeatService(**defaults)


async def test_start_is_idempotent(tmp_path) -> None:
    service = _make_service(tmp_path)

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


async def test_decide_skip_when_no_tool_call(tmp_path) -> None:
    """If the LLM returns plain text (no tool call), decision is 'skip'."""
    from nanobot.providers.base import LLMResponse

    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content="All good, nothing to do."))

    service = _make_service(tmp_path, provider=provider)

    action, tasks = await service._decide("# Heartbeat\nNo pending items.")
    assert action == "skip"
    assert tasks == ""


async def test_decide_run_when_tool_call(tmp_path) -> None:
    """If the LLM calls the heartbeat tool with action=run, extract tasks."""
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "Deploy v2.1"},
                )
            ],
        )
    )

    service = _make_service(tmp_path, provider=provider)

    action, tasks = await service._decide("# Heartbeat\n- Deploy v2.1")
    assert action == "run"
    assert tasks == "Deploy v2.1"


async def test_tick_skips_when_no_heartbeat_file(tmp_path) -> None:
    """Tick should be a silent no-op when HEARTBEAT.md doesn't exist."""
    service = _make_service(tmp_path)
    # Should not raise
    await service._tick()


async def test_tick_executes_on_run(tmp_path) -> None:
    """Full tick: HEARTBEAT.md present -> LLM says run -> on_execute called."""
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    hb_file = tmp_path / "HEARTBEAT.md"
    hb_file.write_text("# Heartbeat\n- Deploy v2.1", encoding="utf-8")

    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="hb_2",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "Deploy v2.1"},
                )
            ],
        )
    )

    on_execute = AsyncMock(return_value="Deployed v2.1 successfully")
    on_notify = AsyncMock()

    service = _make_service(
        tmp_path,
        provider=provider,
        on_execute=on_execute,
        on_notify=on_notify,
    )

    await service._tick()

    on_execute.assert_awaited_once_with("Deploy v2.1")
    on_notify.assert_awaited_once_with("Deployed v2.1 successfully")
