import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatDecision, HeartbeatService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
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

    decision = await service._decide("heartbeat content")
    assert decision.action == "skip"
    assert decision.task_intent == ""
    assert decision.must_keep == []


@pytest.mark.asyncio
async def test_decide_prefers_task_intent_and_preserves_structured_fields(tmp_path) -> None:
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={
                        "action": "run",
                        "tasks": "legacy summary",
                        "task_intent": "do full morning checks",
                        "must_keep": ["must include links", "before 09:30"],
                        "source_refs": ["L2-L4", "L8"],
                    },
                )
            ],
        )
    ])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    decision = await service._decide("heartbeat content")
    assert decision.action == "run"
    assert decision.task_intent == "do full morning checks"
    assert decision.must_keep == ["must include links", "before 09:30"]
    assert decision.source_refs == ["L2-L4", "L8"]


def test_selection_budget_is_per_model_adaptive(tmp_path) -> None:
    provider = DummyProvider([])

    small = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )._selection_budget_for_model()

    large = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-5",
    )._selection_budget_for_model()

    assert large.max_render_chars > small.max_render_chars
    assert large.context_fallback_max_lines >= small.context_fallback_max_lines
    assert large.priority_max_matches >= small.priority_max_matches


def test_build_execution_payload_prioritizes_constraints_and_refs(tmp_path) -> None:
    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    content = "\n".join(
        [
            "# HEARTBEAT",
            "- [ ] check inbox",
            "- [ ] check calendar",
            "notes one",
            "notes two",
            "must include source links",
            "noise a",
            "Deadline: before 09:30",
        ]
        + [f"noise line {i}" for i in range(1, 120)]
    )

    payload = service._build_execution_payload(
        HeartbeatDecision(
            action="run",
            task_intent="run heartbeat",
            must_keep=["must include source links"],
            source_refs=["L2-L3", "L8"],
        ),
        content,
    )

    assert payload.summary == "run heartbeat"
    assert "- [ ] check inbox" in payload.selected_sections
    assert "- [ ] check calendar" in payload.selected_sections
    assert "must include source links" in payload.selected_sections
    assert "Deadline: before 09:30" in payload.selected_sections
    assert payload.dropped_non_empty_lines > 0

    rendered = service._render_execution_input(payload)
    assert "Use the following HEARTBEAT.md context" in rendered
    assert "Context truncated:" in rendered


def test_build_execution_payload_scales_with_model_budget(tmp_path) -> None:
    provider = DummyProvider([])

    small_service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )
    large_service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-5",
    )

    content = "\n".join(["# HEARTBEAT", "- [ ] one task", "must include links", "Deadline: by 09:30"] + [f"noise {i}" for i in range(600)])
    decision = HeartbeatDecision(
        action="run",
        task_intent="run",
        must_keep=["must include links"],
        source_refs=["L2-L4"],
    )

    small = small_service._build_execution_payload(decision, content)
    large = large_service._build_execution_payload(decision, content)

    assert len(large.selected_sections) >= len(small.selected_sections)


@pytest.mark.asyncio
async def test_trigger_now_executes_with_prioritized_context_payload(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text(
        "\n".join(
            [
                "# HEARTBEAT",
                "- [ ] do thing",
                "must not message at night",
                "Deadline: before 09:30",
            ]
            + [f"filler {i}" for i in range(80)]
        ),
        encoding="utf-8",
    )

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={
                        "action": "run",
                        "task_intent": "check open tasks",
                        "must_keep": ["must not message at night"],
                        "source_refs": ["L2-L4"],
                    },
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
    assert len(called_with) == 1
    payload = called_with[0]
    assert "check open tasks" in payload
    assert "- [ ] do thing" in payload
    assert "must not message at night" in payload
    assert "Deadline: before 09:30" in payload


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

    decision = await service._decide("heartbeat content")

    assert decision.action == "run"
    assert decision.task_intent == "check open tasks"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
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

