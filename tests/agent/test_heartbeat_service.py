import asyncio
import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from nanobot.agent.runner import (
    STOP_COMPLETED,
    STOP_EMPTY_FINAL,
    STOP_ERROR,
    STOP_INTENTIONAL_SILENCE,
)
from nanobot.bus.events import OutboundMessage
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE
from nanobot.heartbeat.service import (
    DueTask,
    HeartbeatService,
    MODEL_PRESETS,
    filter_heartbeat_response,
)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_heartbeat(
    tasks_section: str = "",
    announcements_section: str = "",
) -> str:
    parts = ["# Heartbeat Tasks\n"]
    parts.append(f"## Announcements\n{announcements_section}")
    parts.append(f"## User Tasks\n{tasks_section}")
    parts.append("## Completed\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# LLM path (last_run_tracking=False)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks, due_tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""
    assert due_tasks == []


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

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
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

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
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
    date_match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", user_content)
    assert date_match, "prompt does not contain a date/time string"
    assert before <= date_match.group() <= after


@pytest.mark.asyncio
async def test_decide_prompt_requires_due_now(tmp_path) -> None:
    """Phase 1 prompt must tell the LLM to only trigger for tasks due NOW."""
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
    assert "due" in user_content.lower()
    assert "future" in user_content.lower() or "skip" in user_content.lower()


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
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    heartbeat_content = f"""# Heartbeat Tasks

## User Tasks

### Remind: complete Taxes
Schedule: {tomorrow}
Recur: every 1 day
Until: 2099-12-31
Added: 2026-03-09

## Completed
"""
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

async def test_tick_notifies_when_evaluator_says_yes(tmp_path, monkeypatch) -> None:
    """Phase 1 run -> Phase 2 execute -> Phase 3 evaluate=notify -> on_notify called."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check deployments", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check deployments"},
                )
            ],
        ),
    ])

    executed: list[str] = []
    notified: list[str] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        executed.append(tasks)
        return "deployment failed on staging"

    async def _on_notify(response: str) -> None:
        notified.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    async def _eval_notify(*a, **kw):
        return True

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_notify)

    await service._tick()
    assert executed == ["check deployments"]
    assert notified == ["deployment failed on staging"]


@pytest.mark.asyncio
async def test_tick_suppresses_when_evaluator_says_no(tmp_path, monkeypatch) -> None:
    """Phase 1 run -> Phase 2 execute -> Phase 3 evaluate=silent -> on_notify NOT called."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] check status", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check status"},
                )
            ],
        ),
    ])

    executed: list[str] = []
    notified: list[str] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        executed.append(tasks)
        return "everything is fine, no issues"

    async def _on_notify(response: str) -> None:
        notified.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_notify=_on_notify,
    )

    async def _eval_silent(*a, **kw):
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_silent)

    await service._tick()
    assert executed == ["check status"]
    assert notified == []


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

    action, tasks, due_tasks = await service._decide("heartbeat content")

    assert action == "run"
    assert tasks == "check open tasks"
    assert due_tasks == []  # LLM fallback returns empty list
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_decide_falls_back_to_llm_when_tracking_disabled(tmp_path) -> None:
    """With last_run_tracking=False, LLM is always called regardless of task due state."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Remind: something\nSchedule: {past}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )

    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=False,
    )

    await service._decide(content)
    assert provider.calls == 1


# ---------------------------------------------------------------------------
# _compute_due_tasks — announcements
# ---------------------------------------------------------------------------

def test_compute_due_tasks_announcement_always_due() -> None:
    content = _make_heartbeat(
        announcements_section="\n### New Homer update\nMessage: v2 is live.\n"
    )
    due = HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 10, 0))
    assert len(due) == 1
    assert due[0].name == "New Homer update"
    assert due[0].task_type == "announcement"
    assert due[0].schedule is None


def test_compute_due_tasks_empty_announcements_section() -> None:
    content = _make_heartbeat(announcements_section="\n")
    due = HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 10, 0))
    assert due == []


def test_compute_due_tasks_multiple_announcements() -> None:
    content = _make_heartbeat(
        announcements_section="\n### Announcement A\n\n### Announcement B\n"
    )
    due = HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 10, 0))
    names = [t.name for t in due]
    assert "Announcement A" in names
    assert "Announcement B" in names
    assert all(t.task_type == "announcement" for t in due)


# ---------------------------------------------------------------------------
# _compute_due_tasks — reminder tasks
# ---------------------------------------------------------------------------

def test_compute_due_tasks_reminder_due_when_schedule_passed() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Remind: call dentist\nSchedule: {past}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1
    assert due[0].name == "Remind: call dentist"
    assert due[0].task_type == "reminder"
    assert due[0].schedule == past


def test_compute_due_tasks_reminder_not_due_when_schedule_future() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    future = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Remind: call dentist\nSchedule: {future}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert due == []


def test_compute_due_tasks_reminder_due_exactly_on_schedule() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    content = _make_heartbeat(
        "\n### On-time reminder\nSchedule: 2026-03-12 10:00\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1


def test_compute_due_tasks_reminder_not_due_one_minute_before() -> None:
    before = datetime(2026, 3, 12, 9, 59)
    content = _make_heartbeat(
        "\n### 10am reminder\nSchedule: 2026-03-12 10:00\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, before)
    assert due == []


def test_compute_due_tasks_date_only_schedule_fires_on_day() -> None:
    """Date-only schedule (no time) fires at any point on that date."""
    content = _make_heartbeat(
        "\n### Daily reminder\nSchedule: 2026-03-12\nRecur: every 1 day\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    assert HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 9, 0))
    assert not HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 11, 23, 59))


# ---------------------------------------------------------------------------
# _compute_due_tasks — system tasks
# ---------------------------------------------------------------------------

def test_compute_due_tasks_system_task_type() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nRecur: every 1 hour\nRecipients: primary:whatsapp\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1
    assert due[0].task_type == "system"
    assert due[0].name == "Gmail scan"


def test_compute_due_tasks_system_task_not_due() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    future = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Morning briefing\nType: system\nSchedule: {future}\nRecur: every 1 day\nRecipients: primary:whatsapp\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert due == []


# ---------------------------------------------------------------------------
# _compute_due_tasks — Until / expiry
# ---------------------------------------------------------------------------

def test_compute_due_tasks_expired_task_excluded() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    past_sched = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    content = _make_heartbeat(
        f"\n### Old reminder\nSchedule: {past_sched}\nUntil: {yesterday}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert due == []


def test_compute_due_tasks_task_not_expired_until_tomorrow() -> None:
    now = datetime(2026, 3, 12, 10, 0)
    past_sched = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    content = _make_heartbeat(
        f"\n### Active reminder\nSchedule: {past_sched}\nUntil: {tomorrow}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1


# ---------------------------------------------------------------------------
# _compute_due_tasks — mixed / edge cases
# ---------------------------------------------------------------------------

def test_compute_due_tasks_mixed_due_and_future() -> None:
    """Only past-scheduled tasks appear in the due list."""
    now = datetime(2026, 3, 12, 15, 0)
    content = _make_heartbeat(
        "\n### Past task\nSchedule: 2026-03-12 14:00\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n\n"
        "### Future task\nSchedule: 2026-03-12 18:00\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    names = [t.name for t in due]
    assert "Past task" in names
    assert "Future task" not in names


def test_compute_due_tasks_all_three_types() -> None:
    """Announcement + system + reminder all appear when due."""
    now = datetime(2026, 3, 12, 15, 0)
    content = _make_heartbeat(
        announcements_section="\n### Deploy complete\n",
        tasks_section=(
            "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 14:00\nRecur: every 1 hour\nRecipients: primary:whatsapp\n\n"
            "### Remind: pick up kids\nSchedule: 2026-03-12 14:30\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
        ),
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 3
    assert {t.task_type for t in due} == {"announcement", "system", "reminder"}


def test_compute_due_tasks_no_user_tasks_section() -> None:
    content = "# Heartbeat Tasks\n\n## Announcements\n\n## Completed\n"
    due = HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 10, 0))
    assert due == []


def test_compute_due_tasks_no_schedule_field_skipped() -> None:
    """Tasks without a Schedule field are ignored."""
    content = _make_heartbeat("\n### Some task\nAdded: 2026-03-01\n")
    due = HeartbeatService._compute_due_tasks(content, datetime(2026, 3, 12, 10, 0))
    assert due == []


# ---------------------------------------------------------------------------
# Deterministic _decide (last_run_tracking=True)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decide_skips_without_llm_when_no_due_tasks(tmp_path) -> None:
    """With last_run_tracking=True and no due tasks, LLM is NOT called."""
    future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Future task\nSchedule: {future}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )

    provider = DummyProvider([])  # would raise if called
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    action, tasks, due_tasks = await service._decide(content)
    assert action == "skip"
    assert tasks == ""
    assert due_tasks == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_decide_runs_without_llm_when_task_due(tmp_path) -> None:
    """With last_run_tracking=True and a due task, action is 'run' with no LLM call."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Remind: pick up groceries\nSchedule: {past}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )

    provider = DummyProvider([])  # would raise if called
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    action, tasks, due_tasks = await service._decide(content)
    assert action == "run"
    assert "Remind: pick up groceries" in tasks
    assert len(due_tasks) == 1
    assert due_tasks[0].model is None
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_decide_summary_includes_task_type(tmp_path) -> None:
    """The tasks summary includes the type of each due task."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        announcements_section="\n### Big announcement\n",
        tasks_section=f"\n### Gmail scan\nType: system\nSchedule: {past}\nRecur: every 1 hour\nRecipients: primary:whatsapp\n",
    )

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    action, tasks, due_tasks = await service._decide(content)
    assert action == "run"
    assert "announcement" in tasks
    assert "system" in tasks
    assert len(due_tasks) == 2
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_decide_deterministic_skip_then_execute_on_due(tmp_path) -> None:
    """trigger_now fires Phase 2 when a task is due, without touching LLM in Phase 1."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Remind: medication\nSchedule: {past}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([])  # no LLM responses needed
    executed: list[str] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        executed.append(tasks)
        return "reminded"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        last_run_tracking=True,
    )

    result = await service.trigger_now()
    assert result == "reminded"
    assert len(executed) == 1
    assert "Remind: medication" in executed[0]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_decide_deterministic_skips_future_task(tmp_path) -> None:
    """trigger_now returns None for a future task without calling LLM."""
    future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Remind: dinner\nSchedule: {future}\nRecipients: abc:whatsapp\nAdded: 2026-03-01\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([])
    executed: list[str] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
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
    assert executed == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_two_tasks_only_past_one_fires(tmp_path) -> None:
    """With two tasks at different times, only the past-scheduled one is due."""
    now_fixed = datetime(2026, 3, 12, 15, 0)
    heartbeat_content = _make_heartbeat(
        "\n### Remind: lunch (12pm)\nSchedule: 2026-03-12 12:00\nRecipients: abc:whatsapp\nAdded: 2026-03-10\n\n"
        "### Remind: dinner (6pm)\nSchedule: 2026-03-12 18:00\nRecipients: abc:whatsapp\nAdded: 2026-03-10\n"
    )

    due = HeartbeatService._compute_due_tasks(heartbeat_content, now_fixed)
    names = [t.name for t in due]
    assert "Remind: lunch (12pm)" in names
    assert "Remind: dinner (6pm)" not in names

async def test_decide_prompt_includes_current_time(tmp_path) -> None:
    """Phase 1 user prompt must contain current time so the LLM can judge task urgency."""

    captured_messages: list[dict] = []

    class CapturingProvider(LLMProvider):
        async def chat(self, *, messages=None, **kwargs) -> LLMResponse:
            if messages:
                captured_messages.extend(messages)
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1", name="heartbeat",
                        arguments={"action": "skip"},
                    )
                ],
            )

        def get_default_model(self) -> str:
            return "test-model"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=CapturingProvider(),
        model="test-model",
    )

    await service._decide("- [ ] check servers at 10:00 UTC")

    user_msg = captured_messages[1]
    assert user_msg["role"] == "user"
    assert "Current Time:" in user_msg["content"]


# ---------------------------------------------------------------------------
# Per-task model overrides
# ---------------------------------------------------------------------------

def test_compute_due_tasks_parses_model_preset() -> None:
    """Model: flash resolves to the MODEL_PRESETS value."""
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nModel: flash\nRecur: every 1 hour\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1
    assert due[0].model == MODEL_PRESETS["flash"]


def test_compute_due_tasks_parses_model_literal() -> None:
    """Model: with a full model string uses it as-is."""
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Heavy task\nSchedule: {past}\nModel: openai/gpt-4o\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1
    assert due[0].model == "openai/gpt-4o"


def test_compute_due_tasks_no_model_field_returns_none() -> None:
    """Tasks without Model: field get model=None (backward compat)."""
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Simple task\nSchedule: {past}\nRecipients: abc:whatsapp\n"
    )
    due = HeartbeatService._compute_due_tasks(content, now)
    assert len(due) == 1
    assert due[0].model is None


def test_compute_due_tasks_all_presets_resolve() -> None:
    """All preset names resolve to their full model strings."""
    now = datetime(2026, 3, 12, 10, 0)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    for preset, expected in MODEL_PRESETS.items():
        content = _make_heartbeat(
            f"\n### Task {preset}\nSchedule: {past}\nModel: {preset}\n"
        )
        due = HeartbeatService._compute_due_tasks(content, now)
        assert len(due) == 1
        assert due[0].model == expected, f"Preset '{preset}' did not resolve"


@pytest.mark.asyncio
async def test_tick_groups_tasks_by_model(tmp_path, monkeypatch) -> None:
    """Tasks with different models get separate on_execute calls."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nModel: flash\nRecur: every 1 hour\n\n"
        f"### Morning briefing\nType: system\nSchedule: {past}\nModel: pro\nRecur: every 1 day\n\n"
        f"### Remind: call dentist\nSchedule: {past}\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([])
    calls: list[tuple[str, str | None]] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        calls.append((tasks, model_override))
        return "done"

    async def _eval_yes(*a, **kw):
        return False  # suppress notifications for test simplicity

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval_yes)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        last_run_tracking=True,
    )

    await service._tick()

    # Should have 3 groups: flash, pro, None (default)
    assert len(calls) == 3
    models_used = {c[1] for c in calls}
    assert MODEL_PRESETS["flash"] in models_used
    assert MODEL_PRESETS["pro"] in models_used
    assert None in models_used


@pytest.mark.asyncio
async def test_tick_single_model_group(tmp_path, monkeypatch) -> None:
    """All tasks with same model (or no model) run in one on_execute call."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Task A\nSchedule: {past}\n\n"
        f"### Task B\nSchedule: {past}\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([])
    calls: list[tuple[str, str | None]] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        calls.append((tasks, model_override))
        return "done"

    async def _eval(*a, **kw):
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _eval)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        last_run_tracking=True,
    )

    await service._tick()

    # Both tasks have no model -> single group with model_override=None
    assert len(calls) == 1
    assert calls[0][1] is None
    assert "Task A" in calls[0][0]
    assert "Task B" in calls[0][0]


@pytest.mark.asyncio
async def test_trigger_now_groups_by_model(tmp_path) -> None:
    """trigger_now groups tasks by model and calls on_execute for each."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat_content = _make_heartbeat(
        f"\n### Fast task\nSchedule: {past}\nModel: flash\n\n"
        f"### Default task\nSchedule: {past}\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

    provider = DummyProvider([])
    calls: list[tuple[str, str | None]] = []

    async def _on_execute(tasks: str, model_override: str | None = None) -> str:
        calls.append((tasks, model_override))
        return f"done with {model_override}"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        last_run_tracking=True,
    )

    result = await service.trigger_now()
    assert len(calls) == 2
    assert result is not None
    models_used = {c[1] for c in calls}
    assert MODEL_PRESETS["flash"] in models_used
    assert None in models_used


@pytest.mark.asyncio
async def test_decide_returns_due_tasks_with_model(tmp_path) -> None:
    """_decide returns structured DueTask list with model field when last_run_tracking=True."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nModel: haiku\nRecur: every 1 hour\n"
    )

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        last_run_tracking=True,
    )

    action, tasks, due_tasks = await service._decide(content)
    assert action == "run"
    assert len(due_tasks) == 1
    assert due_tasks[0].model == MODEL_PRESETS["haiku"]
    assert due_tasks[0].name == "Gmail scan"


# ---------------------------------------------------------------------------
# Pre-check parsing
# ---------------------------------------------------------------------------

def test_compute_due_tasks_parses_pre_check() -> None:
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Check escalations\nType: system\nSchedule: {past}\n"
        "Recur: every 30 minutes\nPre-check: escalations\n"
    )
    due = HeartbeatService._compute_due_tasks(content, datetime.now())
    assert len(due) == 1
    assert due[0].pre_check == "escalations"


def test_compute_due_tasks_no_pre_check_returns_none() -> None:
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    content = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nRecur: every 1 hour\n"
    )
    due = HeartbeatService._compute_due_tasks(content, datetime.now())
    assert len(due) == 1
    assert due[0].pre_check is None


# ---------------------------------------------------------------------------
# Pre-check execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pre_check_empty_output_returns_false() -> None:
    """Command that outputs nothing → no work."""
    result = await HeartbeatService._run_pre_check("printf ''")
    assert result is False


@pytest.mark.asyncio
async def test_run_pre_check_empty_json_array_returns_false() -> None:
    """Command that outputs [] → no work."""
    result = await HeartbeatService._run_pre_check("echo '[]'")
    assert result is False


@pytest.mark.asyncio
async def test_run_pre_check_skip_output_returns_false() -> None:
    """Command that outputs SKIP → no work."""
    result = await HeartbeatService._run_pre_check("echo 'SKIP: no emails'")
    assert result is False


@pytest.mark.asyncio
async def test_run_pre_check_with_data_returns_true() -> None:
    """Command that outputs real data → has work."""
    result = await HeartbeatService._run_pre_check('echo \'[{"id": "abc"}]\'')
    assert result is True


@pytest.mark.asyncio
async def test_run_pre_check_failure_returns_true() -> None:
    """Command that fails → proceed with LLM to be safe."""
    result = await HeartbeatService._run_pre_check("false")
    assert result is True


@pytest.mark.asyncio
async def test_filter_by_pre_checks_removes_empty_tasks(tmp_path) -> None:
    """Tasks whose pre-check returns empty are filtered out."""
    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        last_run_tracking=True,
        pre_check_registry={"escalations": "echo []"},
    )
    tasks = [
        DueTask(name="Gmail scan", task_type="system", schedule="2026-01-01"),
        DueTask(name="Check escalations", task_type="system", schedule="2026-01-01",
                pre_check="escalations"),
    ]
    result = await service._filter_by_pre_checks(tasks)
    assert len(result) == 1
    assert result[0].name == "Gmail scan"


@pytest.mark.asyncio
async def test_filter_by_pre_checks_keeps_tasks_with_data(tmp_path) -> None:
    """Tasks whose pre-check returns data are kept."""
    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        last_run_tracking=True,
        pre_check_registry={"escalations": "echo [{}]"},
    )
    tasks = [
        DueTask(name="Check escalations", task_type="system", schedule="2026-01-01",
                pre_check="escalations"),
    ]
    result = await service._filter_by_pre_checks(tasks)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_filter_by_pre_checks_unknown_key_proceeds(tmp_path) -> None:
    """Unknown pre-check key → task proceeds to LLM."""
    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        last_run_tracking=True,
        pre_check_registry={},
    )
    tasks = [
        DueTask(name="Check escalations", task_type="system", schedule="2026-01-01",
                pre_check="unknown_key"),
    ]
    result = await service._filter_by_pre_checks(tasks)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_tick_skips_llm_when_pre_check_empty(tmp_path) -> None:
    """Full tick: pre-check returns empty → no LLM call."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat = _make_heartbeat(
        f"\n### Check escalations\nType: system\nSchedule: {past}\n"
        "Recur: every 30 minutes\nPre-check: escalations\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat)

    execute_calls = []

    async def mock_execute(summary: str, model: str | None) -> str:
        execute_calls.append(summary)
        return ""

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        on_execute=mock_execute, last_run_tracking=True,
        pre_check_registry={"escalations": "echo []"},
    )

    await service._tick()
    assert len(execute_calls) == 0, "LLM should not have been called"


@pytest.mark.asyncio
async def test_tick_calls_llm_when_pre_check_has_data(tmp_path) -> None:
    """Full tick: pre-check returns data → LLM called."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat = _make_heartbeat(
        f"\n### Check escalations\nType: system\nSchedule: {past}\n"
        "Recur: every 30 minutes\nPre-check: escalations\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat)

    execute_calls = []

    async def mock_execute(summary: str, model: str | None) -> str:
        execute_calls.append(summary)
        return ""

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        on_execute=mock_execute, last_run_tracking=True,
        pre_check_registry={"escalations": "echo [{}]"},
    )

    await service._tick()
    assert len(execute_calls) == 1, "LLM should have been called"


@pytest.mark.asyncio
async def test_tick_mixed_pre_check_only_runs_tasks_with_work(tmp_path) -> None:
    """Two due tasks: one pre-check empty, one no pre-check → only the latter runs."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nRecur: every 1 hour\n"
        f"\n### Check escalations\nType: system\nSchedule: {past}\n"
        "Recur: every 30 minutes\nPre-check: escalations\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat)

    execute_calls = []

    async def mock_execute(summary: str, model: str | None) -> str:
        execute_calls.append(summary)
        return ""

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path, provider=provider, model="test",
        on_execute=mock_execute, last_run_tracking=True,
        pre_check_registry={"escalations": "echo []"},
    )

    await service._tick()
    assert len(execute_calls) == 1
    assert "Gmail scan" in execute_calls[0]
    assert "Check escalations" not in execute_calls[0]


# ---------------------------------------------------------------------------
# _advance_schedules — deterministic post-execution schedule advancement
# ---------------------------------------------------------------------------

def _fixed_now(dt: datetime):
    """Return a patch context that fixes HeartbeatService._now()."""
    return patch.object(HeartbeatService, "_now", return_value=dt)


@pytest.fixture
def advance_service(tmp_path):
    """Factory fixture for _advance_schedules tests."""
    def _make(heartbeat_content: str) -> HeartbeatService:
        (tmp_path / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")
        return HeartbeatService(
            workspace=tmp_path, provider=DummyProvider([]), model="test",
            last_run_tracking=True, timezone="America/New_York",
        )
    return _make


def test_advance_schedules_daily_task(advance_service) -> None:
    """A daily recurring task's Schedule is advanced past now after execution."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 07:00\nRecur: every 1 day\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 07:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-13 07:00" in updated
    assert "Last-run: 2026-03-12 10:30" in updated


def test_advance_schedules_hourly_task(advance_service) -> None:
    """An hourly recurring task advances Schedule by 1 hour past now."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 09:00\nRecur: every 1 hour\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-12 11:00" in updated


def test_advance_schedules_skips_past_now(advance_service) -> None:
    """When schedule is far in the past, it jumps forward past now."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Balance check\nType: system\nSchedule: 2026-03-10 09:00\nRecur: every 1 day\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Balance check", task_type="system", schedule="2026-03-10 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-13 09:00" in updated


def test_advance_schedules_skips_non_recurring(advance_service) -> None:
    """Tasks without Recur field are not modified."""
    now = datetime(2026, 3, 12, 10, 30)
    past = "2026-03-12 09:00"
    heartbeat = _make_heartbeat(
        f"\n### One-time reminder\nSchedule: {past}\nRecipients: abc:whatsapp\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="One-time reminder", task_type="reminder", schedule=past)]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert f"Schedule: {past}" in updated
    assert "Last-run:" not in updated


def test_advance_schedules_skips_announcements(advance_service) -> None:
    """Announcements (no schedule) are skipped without error."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(announcements_section="\n### Deploy done\n")
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Deploy done", task_type="announcement", schedule=None)]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert updated == heartbeat


def test_advance_schedules_updates_existing_last_run(advance_service) -> None:
    """If Last-run already exists, it is updated rather than duplicated."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 09:00\nLast-run: 2026-03-11 09:00\nRecur: every 1 hour\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert updated.count("Last-run:") == 1
    assert "Last-run: 2026-03-12 10:30" in updated


def test_advance_schedules_multiple_tasks(advance_service) -> None:
    """Multiple due tasks are all advanced in a single call."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 09:00\nRecur: every 1 hour\n\n"
        "### Balance check\nType: system\nSchedule: 2026-03-12 07:00\nRecur: every 1 day\n"
    )
    service = advance_service(heartbeat)
    tasks = [
        DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 09:00"),
        DueTask(name="Balance check", task_type="system", schedule="2026-03-12 07:00"),
    ]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-12 11:00" in updated
    assert "Schedule: 2026-03-13 07:00" in updated


def test_advance_schedules_date_only(advance_service) -> None:
    """Date-only schedule (no time) stays date-only after advancement."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Weekly review\nSchedule: 2026-03-12\nRecur: every 7 days\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Weekly review", task_type="reminder", schedule="2026-03-12")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-19" in updated


def test_advance_schedules_advances_past_until(advance_service) -> None:
    """Schedule is advanced even past Until — _compute_due_tasks handles expiry."""
    now = datetime(2026, 3, 15, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Temp reminder\nSchedule: 2026-03-14 09:00\nRecur: every 1 day\nUntil: 2026-03-14\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Temp reminder", task_type="reminder", schedule="2026-03-14 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    # Schedule IS advanced — _compute_due_tasks won't fire it again (past Until)
    assert "Schedule: 2026-03-16 09:00" in updated


@pytest.mark.asyncio
async def test_tick_advances_schedules_after_execution(tmp_path, monkeypatch) -> None:
    """Full _tick integration: schedules are advanced after on_execute completes."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nRecur: every 1 hour\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat, encoding="utf-8")

    async def mock_execute(summary: str, model: str | None) -> str:
        return "done"

    async def mock_eval(*a, **kw):
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", mock_eval)

    service = HeartbeatService(
        workspace=tmp_path, provider=DummyProvider([]), model="test",
        on_execute=mock_execute, last_run_tracking=True,
    )

    await service._tick()

    updated = (tmp_path / "HEARTBEAT.md").read_text()
    assert f"Schedule: {past}" not in updated
    assert "Last-run:" in updated


def test_advance_schedules_minute_recurrence(advance_service) -> None:
    """Minute-based recurrence advances correctly."""
    now = datetime(2026, 3, 12, 10, 35)
    heartbeat = _make_heartbeat(
        "\n### Frequent check\nType: system\nSchedule: 2026-03-12 10:00\nRecur: every 30 minutes\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Frequent check", task_type="system", schedule="2026-03-12 10:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-12 11:00" in updated


def test_advance_schedules_extra_whitespace(advance_service) -> None:
    """Schedule with extra whitespace after colon is still replaced correctly."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule:  2026-03-12 09:00\nRecur: every 1 hour\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "2026-03-12 11:00" in updated
    assert "2026-03-12 09:00" not in updated


def test_advance_schedules_schedule_at_eof(advance_service) -> None:
    """Last-run is inserted even when Schedule is the last line with no trailing newline."""
    now = datetime(2026, 3, 12, 10, 30)
    content = "# Heartbeat Tasks\n## Announcements\n## User Tasks\n### Task EOF\nType: system\nSchedule: 2026-03-12 09:00\nRecur: every 1 hour"
    service = advance_service(content)
    tasks = [DueTask(name="Task EOF", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "2026-03-12 11:00" in updated
    assert "Last-run: 2026-03-12 10:30" in updated


def test_advance_schedules_weekly_recurrence(advance_service) -> None:
    """Weekly recurrence advances by 7 days."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Weekly standup\nSchedule: 2026-03-12\nRecur: every 1 week\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Weekly standup", task_type="reminder", schedule="2026-03-12")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-19" in updated


def test_advance_schedules_biweekly_recurrence(advance_service) -> None:
    """Bi-weekly recurrence advances by 14 days."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Biweekly review\nSchedule: 2026-03-12\nRecur: every 2 weeks\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Biweekly review", task_type="reminder", schedule="2026-03-12")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-26" in updated


def test_advance_schedules_zero_recurrence_defaults_to_one(advance_service) -> None:
    """Recur: every 0 days defaults to 1 day to prevent infinite loops."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Bad task\nSchedule: 2026-03-12 09:00\nRecur: every 0 days\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Bad task", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    # 0 days treated as 1 day
    assert "Schedule: 2026-03-13 09:00" in updated


def test_advance_schedules_block_stops_at_section_boundary(advance_service) -> None:
    """Block regex stops at ## section headers, not just ### task headers."""
    now = datetime(2026, 3, 12, 10, 30)
    heartbeat = _make_heartbeat(
        "\n### Last task\nType: system\nSchedule: 2026-03-12 09:00\nRecur: every 1 hour\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Last task", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    assert "Schedule: 2026-03-12 11:00" in updated
    # Verify ## Completed section is untouched
    assert "## Completed" in updated


def test_advance_schedules_skips_already_advanced(advance_service) -> None:
    """If the LLM already ticked the schedule forward, don't double-advance."""
    now = datetime(2026, 3, 12, 10, 30)
    # Schedule is already in the future (LLM called --tick during execution)
    heartbeat = _make_heartbeat(
        "\n### Gmail scan\nType: system\nSchedule: 2026-03-12 11:00\nRecur: every 1 hour\n"
    )
    service = advance_service(heartbeat)
    tasks = [DueTask(name="Gmail scan", task_type="system", schedule="2026-03-12 09:00")]

    with _fixed_now(now):
        service._advance_schedules(tasks)

    updated = service.heartbeat_file.read_text()
    # Should stay at 11:00, NOT advance to 12:00
    assert "Schedule: 2026-03-12 11:00" in updated


@pytest.mark.asyncio
async def test_tick_advances_per_group_on_failure(tmp_path, monkeypatch) -> None:
    """If one task group fails, the other group's schedule is still advanced."""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    heartbeat = _make_heartbeat(
        f"\n### Gmail scan\nType: system\nSchedule: {past}\nModel: flash\nRecur: every 1 hour\n\n"
        f"### Balance check\nType: system\nSchedule: {past}\nModel: pro\nRecur: every 1 day\n"
    )
    (tmp_path / "HEARTBEAT.md").write_text(heartbeat, encoding="utf-8")

    call_count = 0

    async def mock_execute(summary: str, model: str | None) -> str:
        nonlocal call_count
        call_count += 1
        if "Balance check" in summary:
            raise RuntimeError("API error")
        return "done"

    async def mock_eval(*a, **kw):
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", mock_eval)

    service = HeartbeatService(
        workspace=tmp_path, provider=DummyProvider([]), model="test",
        on_execute=mock_execute, last_run_tracking=True,
    )

    await service._tick()

    updated = (tmp_path / "HEARTBEAT.md").read_text()
    # Both tasks should be advanced — even Balance check (failed) gets advanced
    # to prevent retry spam on persistent errors
    gmail_block = updated.split("### Gmail scan")[1].split("###")[0]
    assert f"Schedule: {past}" not in gmail_block
    assert "Last-run:" in gmail_block
    balance_block = updated.split("### Balance check")[1].split("##")[0]
    assert f"Schedule: {past}" not in balance_block
    assert "Last-run:" in balance_block
    assert call_count == 2


# ---------------------------------------------------------------------------
# filter_heartbeat_response — stop_reason-based suppression logic
# ---------------------------------------------------------------------------

def _make_resp(content: str, stop_reason: str = STOP_COMPLETED) -> OutboundMessage:
    return OutboundMessage(channel="whatsapp", chat_id="user", content=content, stop_reason=stop_reason)


class TestFilterHeartbeatResponse:

    def test_none_response_returns_empty(self):
        assert filter_heartbeat_response(None, "Gmail scan") == ""

    def test_completed_returns_content(self):
        resp = _make_resp("You have 3 new emails.")
        assert filter_heartbeat_response(resp, "Gmail scan") == "You have 3 new emails."

    def test_completed_none_content_returns_empty(self):
        resp = _make_resp("", stop_reason=STOP_COMPLETED)
        assert filter_heartbeat_response(resp, "Gmail scan") == ""

    def test_empty_final_suppressed(self):
        resp = _make_resp("I completed the tool steps but couldn't produce a final answer.", stop_reason=STOP_EMPTY_FINAL)
        assert filter_heartbeat_response(resp, "Gmail scan") == ""

    def test_llm_echoed_empty_message_suppressed(self):
        """LLM mimics EMPTY_FINAL_RESPONSE_MESSAGE from session history."""
        resp = _make_resp(EMPTY_FINAL_RESPONSE_MESSAGE, stop_reason=STOP_COMPLETED)
        assert filter_heartbeat_response(resp, "Gmail scan") == ""

    def test_error_notifies_admin_by_default(self):
        resp = _make_resp("Sorry, I encountered an error.", stop_reason=STOP_ERROR)
        result = filter_heartbeat_response(resp, "Gmail scan")
        assert "⚠️" in result
        assert "Gmail scan" in result

    def test_error_suppressed_when_suppress_errors_true(self):
        resp = _make_resp("Sorry, I encountered an error.", stop_reason=STOP_ERROR)
        assert filter_heartbeat_response(resp, "Gmail scan", suppress_errors=True) == ""

    def test_error_notification_includes_task_name(self):
        resp = _make_resp("error", stop_reason=STOP_ERROR)
        result = filter_heartbeat_response(resp, "Balance check (system)")
        assert "Balance check (system)" in result

    def test_intentional_silence_returns_empty(self):
        """Heartbeat turn that completed silently by design — MessageTool
        already delivered the user-visible output, so the trailing empty
        turn should be silenced without logging as a failure."""
        resp = _make_resp("", stop_reason=STOP_INTENTIONAL_SILENCE)
        assert filter_heartbeat_response(resp, "Gmail scan") == ""

    def test_intentional_silence_distinct_from_empty_final(self, caplog):
        """Intentional silence should log at debug (benign), while empty-final
        still logs at info (worth watching as a potential model regression)."""
        import logging
        from loguru import logger as loguru_logger

        handler_id = loguru_logger.add(caplog.handler, level="DEBUG", format="{message}")
        try:
            with caplog.at_level(logging.DEBUG):
                filter_heartbeat_response(
                    _make_resp("", stop_reason=STOP_INTENTIONAL_SILENCE),
                    "Gmail scan",
                )
                filter_heartbeat_response(
                    _make_resp(EMPTY_FINAL_RESPONSE_MESSAGE, stop_reason=STOP_EMPTY_FINAL),
                    "Morning briefing",
                )
        finally:
            loguru_logger.remove(handler_id)

        messages = [rec.message for rec in caplog.records]
        # Intentional silence is benign — logged with "by design" marker
        assert any("silent turn (by design)" in m for m in messages)
        # Empty-final is worth seeing in default logs — logged as "suppressed empty response"
        assert any("suppressed empty response" in m for m in messages)
