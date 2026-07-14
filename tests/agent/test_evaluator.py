import pytest

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.evaluator import (
    EVALUATOR_PROMPT_MAX_CHARS,
    default_evaluator_prompt,
    evaluate_response,
    evaluator_prompt_file,
    resolve_evaluator_prompt,
)


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


def _eval_tool_call(should_notify: bool, reason: str = "") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="eval_1",
                name="evaluate_notification",
                arguments={"should_notify": should_notify, "reason": reason},
            )
        ],
    )


_EVAL_PROMPT = "You are a notification gate. Call evaluate_notification."


def test_resolve_evaluator_prompt_uses_workspace_override(tmp_path) -> None:
    path = evaluator_prompt_file(tmp_path)
    path.parent.mkdir()
    path.write_text("Custom evaluator prompt.\n", encoding="utf-8")

    assert resolve_evaluator_prompt(tmp_path) == "Custom evaluator prompt."


def test_resolve_evaluator_prompt_uses_default_for_empty_override(tmp_path) -> None:
    path = evaluator_prompt_file(tmp_path)
    path.parent.mkdir()
    path.write_text("  \n", encoding="utf-8")

    assert resolve_evaluator_prompt(tmp_path) == default_evaluator_prompt()


def test_resolve_evaluator_prompt_caps_workspace_override(tmp_path) -> None:
    path = evaluator_prompt_file(tmp_path)
    path.parent.mkdir()
    path.write_text("x" * (EVALUATOR_PROMPT_MAX_CHARS + 1), encoding="utf-8")

    prompt = resolve_evaluator_prompt(tmp_path)

    assert prompt.startswith("x" * EVALUATOR_PROMPT_MAX_CHARS)
    assert prompt.endswith("... (truncated)")


@pytest.mark.asyncio
async def test_should_notify_true() -> None:
    provider = DummyProvider([_eval_tool_call(True, "user asked to be reminded")])
    result = await evaluate_response(
        "Task completed with results", "check emails", provider, "m",
        evaluator_prompt=_EVAL_PROMPT,
    )
    assert result is True


@pytest.mark.asyncio
async def test_should_notify_false() -> None:
    provider = DummyProvider([_eval_tool_call(False, "routine check, nothing new")])
    result = await evaluate_response(
        "All clear, no updates", "check status", provider, "m",
        evaluator_prompt=_EVAL_PROMPT,
    )
    assert result is False


@pytest.mark.asyncio
async def test_fallback_on_error() -> None:
    class FailingProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            raise RuntimeError("provider down")

    provider = FailingProvider([])
    result = await evaluate_response(
        "some response", "some task", provider, "m",
        evaluator_prompt=_EVAL_PROMPT, default_notify=True,
    )
    assert result is True


@pytest.mark.asyncio
async def test_no_tool_call_fallback() -> None:
    provider = DummyProvider([LLMResponse(content="I think you should notify", tool_calls=[])])
    result = await evaluate_response(
        "some response", "some task", provider, "m",
        evaluator_prompt=_EVAL_PROMPT, default_notify=True,
    )
    assert result is True


@pytest.mark.asyncio
async def test_fail_closed_on_error() -> None:
    class FailingProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            raise RuntimeError("provider down")

    provider = FailingProvider([])
    result = await evaluate_response(
        "some", "task", provider, "m",
        evaluator_prompt=_EVAL_PROMPT, default_notify=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_fail_closed_on_no_tool_call() -> None:
    provider = DummyProvider([LLMResponse(content="text only", tool_calls=[])])
    result = await evaluate_response(
        "some", "task", provider, "m",
        evaluator_prompt=_EVAL_PROMPT, default_notify=False,
    )
    assert result is False
