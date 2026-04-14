import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatService
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


class CapturingProvider(LLMProvider):
    """Provider that records every (model, messages) pair passed to chat()."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__()
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, messages=None, model=None, **kwargs) -> LLMResponse:
        self.calls.append({"model": model, "messages": messages})
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "default-model"


def _run_response() -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="hb_1",
                name="heartbeat",
                arguments={"action": "run", "tasks": "check things"},
            )
        ],
    )


@pytest.mark.asyncio
async def test_decide_uses_eval_model_when_set(tmp_path) -> None:
    """Phase 1 _decide() must pass eval_model to the provider, not the default model."""
    provider = CapturingProvider([_run_response()])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="default-model",
        eval_model="cheap-eval-model",
    )

    await service._decide("content")

    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "cheap-eval-model"


@pytest.mark.asyncio
async def test_decide_falls_back_to_model_when_eval_model_not_set(tmp_path) -> None:
    """When eval_model is not provided it defaults to model."""
    provider = CapturingProvider([_run_response()])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="default-model",
    )

    await service._decide("content")

    assert provider.calls[0]["model"] == "default-model"


@pytest.mark.asyncio
async def test_tick_uses_exec_model_for_evaluate_response(tmp_path, monkeypatch) -> None:
    """Phase 2 post-execution evaluate_response() must receive exec_model."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    provider = CapturingProvider([_run_response()])

    captured_eval_model: list[str] = []

    async def _fake_evaluate(response, tasks, prov, model):
        captured_eval_model.append(model)
        return False  # silence notification

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _fake_evaluate)

    async def _on_execute(_tasks: str) -> str:
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="default-model",
        exec_model="exec-model",
        on_execute=_on_execute,
    )

    await service._tick()

    assert captured_eval_model == ["exec-model"]


@pytest.mark.asyncio
async def test_tick_exec_model_defaults_to_model_when_not_set(tmp_path, monkeypatch) -> None:
    """When exec_model is not provided evaluate_response receives the default model."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    provider = CapturingProvider([_run_response()])

    captured_eval_model: list[str] = []

    async def _fake_evaluate(response, tasks, prov, model):
        captured_eval_model.append(model)
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _fake_evaluate)

    async def _on_execute(_tasks: str) -> str:
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="default-model",
        on_execute=_on_execute,
    )

    await service._tick()

    assert captured_eval_model == ["default-model"]


@pytest.mark.asyncio
async def test_eval_model_and_exec_model_are_independent(tmp_path, monkeypatch) -> None:
    """eval_model and exec_model can differ from each other and from the default model."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    provider = CapturingProvider([_run_response()])

    captured_eval_model: list[str] = []

    async def _fake_evaluate(response, tasks, prov, model):
        captured_eval_model.append(model)
        return False

    monkeypatch.setattr("nanobot.utils.evaluator.evaluate_response", _fake_evaluate)

    async def _on_execute(_tasks: str) -> str:
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="expensive-default",
        eval_model="free-eval-model",
        exec_model="mid-tier-exec-model",
        on_execute=_on_execute,
    )

    await service._tick()

    # Phase 1 used free-eval-model
    assert provider.calls[0]["model"] == "free-eval-model"
    # Phase 2 post-eval used mid-tier-exec-model
    assert captured_eval_model == ["mid-tier-exec-model"]

