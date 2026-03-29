import asyncio
import re
from datetime import datetime, timedelta

import pytest

from nanobot.heartbeat.service import DueTask, HeartbeatService
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

    async def _on_execute(tasks: str) -> str:
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

    async def _on_execute(tasks: str) -> str:
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

    action, tasks = await service._decide("heartbeat content")

    assert action == "run"
    assert tasks == "check open tasks"
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

    action, tasks = await service._decide(content)
    assert action == "skip"
    assert tasks == ""
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

    action, tasks = await service._decide(content)
    assert action == "run"
    assert "Remind: pick up groceries" in tasks
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

    action, tasks = await service._decide(content)
    assert action == "run"
    assert "announcement" in tasks
    assert "system" in tasks
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

    async def _on_execute(tasks: str) -> str:
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
