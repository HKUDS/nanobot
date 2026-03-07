import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatDecision, HeartbeatService
from nanobot.providers.base import LLMResponse, ToolCallRequest


class DummyProvider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return self._responses.pop(0) if self._responses else LLMResponse(content="", tool_calls=[])


def mk_service(tmp_path, provider=None, **kwargs):
    return HeartbeatService(
        workspace=tmp_path,
        provider=provider or DummyProvider([]),
        model=kwargs.pop("model", "openai/gpt-4o-mini"),
        **kwargs,
    )


def tool_resp(arguments: dict) -> LLMResponse:
    return LLMResponse(content="", tool_calls=[ToolCallRequest(id="hb_1", name="heartbeat", arguments=arguments)])


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    service = mk_service(tmp_path, interval_s=9999, enabled=True)
    await service.start()
    first_task = service._task
    await service.start()
    assert service._task is first_task
    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    service = mk_service(tmp_path, provider=DummyProvider([LLMResponse(content="no tool call", tool_calls=[])]))
    decision = await service._decide("heartbeat content")
    assert (decision.action, decision.task_intent, decision.must_keep) == ("skip", "", [])


@pytest.mark.asyncio
async def test_decide_prefers_task_intent_and_preserves_structured_fields(tmp_path) -> None:
    service = mk_service(
        tmp_path,
        provider=DummyProvider([
            tool_resp({
                "action": "run",
                "tasks": "legacy summary",
                "task_intent": "do full morning checks",
                "must_keep": ["must include links", "before 09:30"],
                "source_refs": ["L2-L4", "L8"],
            })
        ]),
    )
    decision = await service._decide("heartbeat content")
    assert decision.action == "run"
    assert decision.task_intent == "do full morning checks"
    assert decision.must_keep == ["must include links", "before 09:30"]
    assert decision.source_refs == ["L2-L4", "L8"]


def test_selection_budget_uses_neutral_fallback_without_model_hardcode(tmp_path) -> None:
    a = mk_service(tmp_path, model="openai/gpt-4o-mini")._selection_budget_for_model()
    b = mk_service(tmp_path, model="openai/gpt-5")._selection_budget_for_model()
    assert a.max_render_chars == b.max_render_chars
    assert a.context_fallback_max_lines == b.context_fallback_max_lines
    assert a.priority_max_matches == b.priority_max_matches


def test_context_window_allows_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_HEARTBEAT_CONTEXT_WINDOW_TOKENS", "64000")
    service = mk_service(tmp_path, model="custom/unknown-model")
    assert service._context_window_tokens_for_model() == 64000


def test_build_execution_payload_prioritizes_constraints_and_refs(tmp_path) -> None:
    service = mk_service(tmp_path)
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
        HeartbeatDecision("run", "run heartbeat", ["must include source links"], ["L2-L3", "L8"]),
        content,
    )
    assert payload.summary == "run heartbeat"
    assert "- [ ] check inbox" in payload.selected_sections
    assert "- [ ] check calendar" in payload.selected_sections
    assert "must include source links" in payload.selected_sections
    assert "Deadline: before 09:30" in payload.selected_sections

    rendered = service._render_execution_input(payload)
    assert "Use the following HEARTBEAT.md context" in rendered
    if payload.dropped_non_empty_lines > 0:
        assert "Context truncated:" in rendered


@pytest.mark.asyncio
async def test_trigger_now_executes_with_prioritized_context_payload(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text(
        "\n".join(["# HEARTBEAT", "- [ ] do thing", "must not message at night", "Deadline: before 09:30"] + [f"filler {i}" for i in range(80)]),
        encoding="utf-8",
    )
    service = mk_service(
        tmp_path,
        provider=DummyProvider([
            tool_resp(
                {
                    "action": "run",
                    "task_intent": "check open tasks",
                    "must_keep": ["must not message at night"],
                    "source_refs": ["L2-L4"],
                }
            )
        ]),
    )

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service.on_execute = _on_execute
    result = await service.trigger_now()
    assert result == "done" and len(called_with) == 1
    payload = called_with[0]
    for needle in ("check open tasks", "- [ ] do thing", "must not message at night", "Deadline: before 09:30"):
        assert needle in payload


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")
    async def _on_execute(tasks: str) -> str:
        return tasks

    service = mk_service(tmp_path, provider=DummyProvider([tool_resp({"action": "skip"})]), on_execute=_on_execute)
    assert await service.trigger_now() is None
