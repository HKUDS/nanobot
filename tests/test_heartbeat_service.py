import asyncio
import re
from datetime import datetime

import pytest

from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.last_messages: list[dict] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        self.last_messages = kwargs.get("messages") or (args[0] if args else [])
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert called_with == ["check open tasks"]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    assert await service.trigger_now() is None


@pytest.mark.asyncio
async def test_decide_prompt_includes_current_datetime(tmp_path) -> None:
    """Phase 1 prompt must include the current date/time so the LLM can evaluate due dates."""
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    before = datetime.now().strftime("%Y-%m-%d %H:%M")
    await service._decide("some heartbeat content")
    after = datetime.now().strftime("%Y-%m-%d %H:%M")

    assert provider.last_messages, "provider was not called"
    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    # The prompt must contain a date string matching YYYY-MM-DD HH:MM
    date_match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", user_content)
    assert date_match, "prompt does not contain a date/time string"
    # The extracted timestamp must be within the before/after window
    assert before <= date_match.group() <= after


@pytest.mark.asyncio
async def test_decide_prompt_requires_due_now(tmp_path) -> None:
    """Phase 1 prompt must tell the LLM to only trigger for tasks due NOW, not future ones."""
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    await service._decide("some heartbeat content")

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    # Must instruct the LLM to check whether tasks are due now
    assert "due" in user_content.lower()
    assert "future" in user_content.lower() or "skip" in user_content.lower()


@pytest.mark.asyncio
async def test_decide_prompt_includes_last_run_awareness(tmp_path) -> None:
    """Phase 1 prompt must tell the LLM to skip tasks whose Last-run matches today."""
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    await service._decide("some heartbeat content")

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "last-run" in user_content.lower()
    # Today's date must appear so the LLM can compare it against the Last-run field
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in user_content


@pytest.mark.asyncio
async def test_trigger_now_returns_none_for_future_recurring_task(tmp_path) -> None:
    """A recurring task scheduled for tomorrow must not trigger execution today."""
    tomorrow = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                .replace(day=datetime.now().day + 1)).strftime("%Y-%m-%d")
    heartbeat_content = f"""# Heartbeat Tasks

## User Tasks

### Remind: complete Taxes
Schedule: {tomorrow}
Recur: every 1 day
Until: 2026-03-13
Added: 2026-03-09

## Completed
"""
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    # Phase 1 correctly recognises tomorrow's date is not due and returns skip
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})
            ],
        )
    ])

    executed: list[str] = []

    async def _on_execute(tasks: str) -> str:
        executed.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result is None
    assert executed == [], "Phase 2 must not run for a future-dated task"


@pytest.mark.asyncio
async def test_trigger_now_skips_task_already_run_today(tmp_path) -> None:
    """A task whose Last-run matches today must not trigger execution again."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_run = datetime.now().strftime("%Y-%m-%d %H:%M")
    heartbeat_content = f"""# Heartbeat Tasks

## User Tasks

### Remind: complete Taxes
Schedule: {today}
Last-run: {today_run}
Recur: every 1 day
Until: 2026-03-13
Added: 2026-03-09

## Completed
"""
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    # Phase 1 sees Last-run matches today and returns skip
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})
            ],
        )
    ])

    executed: list[str] = []

    async def _on_execute(tasks: str) -> str:
        executed.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result is None
    assert executed == [], "Phase 2 must not run when Last-run matches today"


@pytest.mark.asyncio
async def test_two_same_day_tasks_fire_independently(tmp_path) -> None:
    """12pm task already ran (Last-run today) must not suppress the 6pm task."""
    today = datetime.now().strftime("%Y-%m-%d")
    today_run = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Simulate state at 5:50pm: 12pm task has Last-run today, 6pm task has not run yet
    heartbeat_content = f"""# Heartbeat Tasks

## User Tasks

### Remind: bla (12pm)
Schedule: {today} 12:00
Last-run: {today_run}
Recur: every 1 day
Until: 2026-03-13
Added: 2026-03-10

### Remind: bla (6pm)
Schedule: {today} 18:00
Recur: every 1 day
Until: 2026-03-13
Added: 2026-03-10

## Completed
"""
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    # Phase 1 should say "run" because the 6pm task is due (no Last-run)
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "Remind: bla (6pm) is due"},
                )
            ],
        )
    ])

    executed: list[str] = []

    async def _on_execute(tasks: str) -> str:
        executed.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert executed == ["Remind: bla (6pm) is due"], "6pm task must fire even though 12pm task already ran"

    # Also verify the prompt contains both tasks so the LLM has full context
    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "12pm" in user_content
    assert "6pm" in user_content
    assert "Last-run" in user_content


@pytest.mark.asyncio
async def test_decide_retries_transient_error_then_succeeds(tmp_path, monkeypatch) -> None:
    provider = DummyProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        ),
    ])

    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")

    assert action == "run"
    assert tasks == "check open tasks"
    assert provider.calls == 2
    assert delays == [1]
