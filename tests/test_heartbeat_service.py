import asyncio
import re
from datetime import datetime, timedelta

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
async def test_decide_prompt_includes_last_run_awareness_when_enabled(tmp_path) -> None:
    """Phase 1 prompt includes Last-run instruction when last_run_tracking=True."""
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    await service._decide("some heartbeat content")

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "last-run" in user_content.lower()
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in user_content


@pytest.mark.asyncio
async def test_decide_prompt_omits_last_run_when_disabled(tmp_path) -> None:
    """Phase 1 prompt must NOT mention Last-run when last_run_tracking=False (default)."""
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=False,
    )

    await service._decide("some heartbeat content")

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "last-run" not in user_content.lower()


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
        last_run_tracking=True,
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
        last_run_tracking=True,
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


# ---------------------------------------------------------------------------
# _compute_task_statuses unit tests
# ---------------------------------------------------------------------------

def _make_heartbeat(tasks_section: str) -> str:
    return f"# Heartbeat Tasks\n\n## User Tasks\n{tasks_section}\n## Completed\n"


def test_compute_task_statuses_due_when_schedule_passed() -> None:
    """Task with Schedule 1 hour ago appears as DUE NOW."""
    now = datetime(2026, 3, 12, 10, 0)
    schedule_dt = now - timedelta(hours=1)
    schedule_str = schedule_dt.strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Gmail scan\nSchedule: {schedule_str}\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    result = HeartbeatService._compute_task_statuses(content, now)
    assert "IS DUE NOW" in result
    assert "Gmail scan" in result


def test_compute_task_statuses_not_due_when_schedule_future() -> None:
    """Task with Schedule 1 hour from now appears as NOT due."""
    now = datetime(2026, 3, 12, 10, 0)
    schedule_dt = now + timedelta(hours=1)
    schedule_str = schedule_dt.strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Daily morning briefing\nSchedule: {schedule_str}\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    result = HeartbeatService._compute_task_statuses(content, now)
    assert "is NOT due" in result
    assert "Daily morning briefing" in result
    assert "IS DUE NOW" not in result


def test_compute_task_statuses_expired_task_excluded() -> None:
    """Task with Until yesterday is excluded from output entirely."""
    now = datetime(2026, 3, 12, 10, 0)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    schedule_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Old task\nSchedule: {schedule_str}\nUntil: {yesterday}\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    result = HeartbeatService._compute_task_statuses(content, now)
    assert result == ""


def test_compute_task_statuses_datetime_precision() -> None:
    """Task at 10:00: NOT due at 09:59, DUE NOW at exactly 10:00."""
    content = _make_heartbeat(
        "\n### Precise task\nSchedule: 2026-03-12 10:00\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    # One minute before: not due
    before = datetime(2026, 3, 12, 9, 59)
    result_before = HeartbeatService._compute_task_statuses(content, before)
    assert "is NOT due" in result_before
    assert "IS DUE NOW" not in result_before

    # Exactly on time: due now
    on_time = datetime(2026, 3, 12, 10, 0)
    result_on_time = HeartbeatService._compute_task_statuses(content, on_time)
    assert "IS DUE NOW" in result_on_time


def test_compute_task_statuses_empty_when_no_schedule_fields() -> None:
    """HEARTBEAT.md with tasks but no Schedule fields → returns ''."""
    content = _make_heartbeat(
        "\n### Some task\nAdded: 2026-03-01\n"
    )
    result = HeartbeatService._compute_task_statuses(content, datetime(2026, 3, 12, 10, 0))
    assert result == ""


def test_compute_task_statuses_multiple_tasks_mixed() -> None:
    """One due task and one future task both appear with correct labels."""
    now = datetime(2026, 3, 12, 10, 0)
    past_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    future_str = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Past task\nSchedule: {past_str}\nRecur: every 1 day\nAdded: 2026-03-01\n\n"
        f"### Future task\nSchedule: {future_str}\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    result = HeartbeatService._compute_task_statuses(content, now)
    assert "Past task" in result
    assert "IS DUE NOW" in result
    assert "Future task" in result
    assert "is NOT due" in result


@pytest.mark.asyncio
async def test_decide_prompt_includes_computed_statuses_when_tracking_enabled(tmp_path) -> None:
    """When last_run_tracking=True and there's a past-schedule task, prompt contains
    'IS DUE NOW' and 'authoritative'."""
    now = datetime.now()
    past_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Gmail scan\nSchedule: {past_str}\nRecur: every 1 day\nAdded: 2026-03-01\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    await service._decide(heartbeat_content)

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "IS DUE NOW" in user_content
    assert "authoritative" in user_content


@pytest.mark.asyncio
async def test_decide_prompt_uses_fallback_when_no_scheduled_tasks(tmp_path) -> None:
    """When last_run_tracking=True but no Schedule fields, prompt still contains 'Last-run'."""
    heartbeat_content = _make_heartbeat(
        "\n### Some task\nAdded: 2026-03-01\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    await service._decide(heartbeat_content)

    user_content = next(
        m["content"] for m in provider.last_messages if m["role"] == "user"
    )
    assert "Last-run" in user_content
    assert "IS DUE NOW" not in user_content
