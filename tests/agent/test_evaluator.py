import pytest

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.evaluator import evaluate_response


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


@pytest.mark.asyncio
async def test_should_notify_true() -> None:
    provider = DummyProvider([_eval_tool_call(True, "user asked to be reminded")])
    result = await evaluate_response("Task completed with results", "check emails", provider, "m")
    assert result is True


@pytest.mark.asyncio
async def test_should_notify_false() -> None:
    provider = DummyProvider([_eval_tool_call(False, "routine check, nothing new")])
    result = await evaluate_response("All clear, no updates", "check status", provider, "m")
    assert result is False


@pytest.mark.asyncio
async def test_fallback_on_error() -> None:
    class FailingProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            raise RuntimeError("provider down")

    provider = FailingProvider([])
    result = await evaluate_response("some response", "some task", provider, "m")
    assert result is True


@pytest.mark.asyncio
async def test_no_tool_call_fallback() -> None:
    provider = DummyProvider([LLMResponse(content="I think you should notify", tool_calls=[])])
    result = await evaluate_response("some response", "some task", provider, "m")
    assert result is True


@pytest.mark.asyncio
async def test_reminder_should_always_notify() -> None:
    """Test that user-scheduled reminders are always delivered."""
    provider = DummyProvider([_eval_tool_call(True, "user reminder must be delivered")])
    result = await evaluate_response(
        "Time to take a bath 🛁",
        "Remind me in 2 minutes to take a bath",
        provider,
        "m"
    )
    assert result is True


@pytest.mark.asyncio
async def test_cron_reminder_with_context() -> None:
    """Test that cron job reminders with context are delivered."""
    provider = DummyProvider([_eval_tool_call(True, "scheduled reminder")])
    result = await evaluate_response(
        "Here's your daily reminder to check the server logs",
        "[Scheduled Task] Timer finished. Task 'daily-check' has been triggered. Scheduled instruction: Remind me daily to check server logs",
        provider,
        "m"
    )
    assert result is True
