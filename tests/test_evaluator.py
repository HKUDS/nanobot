import pytest

from nanobot.utils.evaluator import evaluate_response, should_publish
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


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


def _eval_tool_call(level: str, reason: str = "") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="eval_1",
                name="evaluate_background_result",
                arguments={"level": level, "reason": reason},
            )
        ],
    )


@pytest.mark.asyncio
async def test_returns_normal_level() -> None:
    provider = DummyProvider([_eval_tool_call("normal", "routine success")])
    result = await evaluate_response("Task completed with results", "check emails", provider, "m")
    assert result == "normal"


@pytest.mark.asyncio
async def test_returns_error_level() -> None:
    provider = DummyProvider([_eval_tool_call("error", "service is failing")])
    result = await evaluate_response("All clear, no updates", "check status", provider, "m")
    assert result == "error"


@pytest.mark.asyncio
async def test_fallback_on_error() -> None:
    class FailingProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            raise RuntimeError("provider down")

    provider = FailingProvider([])
    result = await evaluate_response("some response", "some task", provider, "m")
    assert result == "error"


@pytest.mark.asyncio
async def test_no_tool_call_fallback() -> None:
    provider = DummyProvider([LLMResponse(content="I think you should notify", tool_calls=[])])
    result = await evaluate_response("some response", "some task", provider, "m")
    assert result == "error"


@pytest.mark.parametrize(
    ("level", "policy", "expected"),
    [
        ("normal", "all", True),
        ("error", "all", True),
        ("normal", "error", False),
        ("error", "error", True),
        ("normal", "silent", False),
        ("error", "silent", False),
    ],
)
def test_should_publish(level: str, policy: str, expected: bool) -> None:
    assert should_publish(level, policy) is expected
